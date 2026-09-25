"""Isolated single-point PySCF worker; imports no platform modules."""

from __future__ import annotations

import importlib
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from caddsuite_worker.runtime import EventReporter, WorkerFailure, main

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+*/().-]{0,127}$")
_ELEMENT = re.compile(r"^[A-Z][a-z]?$")


def _run(request: dict[str, Any], reporter: EventReporter) -> dict[str, Any]:
    payload = request["payload"]
    required = (
        "geometry_block",
        "method",
        "basis",
        "charge",
        "multiplicity",
        "max_cycle",
        "memory_mb",
    )
    if any(key not in payload for key in required):
        raise WorkerFailure("PYSCF.REQUEST_INVALID", "required PySCF task settings are missing")
    if payload["protocol"] != "single_point":
        raise WorkerFailure(
            "PYSCF.PROTOCOL_UNSUPPORTED", "only single-point calculations are supported"
        )
    workdir = Path.cwd().resolve(strict=True)
    raw_geometry = payload["geometry_block"]
    if not isinstance(raw_geometry, str) or len(raw_geometry) > 2_000_000:
        raise WorkerFailure("PYSCF.GEOMETRY_INVALID", "geometry block is missing or too large")
    method = payload["method"]
    basis = payload["basis"]
    if not isinstance(method, str) or not isinstance(basis, str):
        raise WorkerFailure("PYSCF.MODEL_INVALID", "method and basis must be strings")
    try:
        integer_fields = ("charge", "multiplicity", "max_cycle", "memory_mb", "n_threads")
        if any(isinstance(payload[key], bool) for key in integer_fields):
            raise ValueError("boolean is not a valid integer setting")
        charge = int(payload["charge"])
        multiplicity = int(payload["multiplicity"])
        max_cycle = int(payload["max_cycle"])
        memory_mb = int(payload["memory_mb"])
        n_threads = int(payload["n_threads"])
    except (ValueError, TypeError) as exc:
        raise WorkerFailure("PYSCF.REQUEST_INVALID", "integer settings are invalid") from exc
    if multiplicity < 1 or max_cycle < 1 or memory_mb < 256 or not 1 <= n_threads <= 256:
        raise WorkerFailure(
            "PYSCF.REQUEST_INVALID", "spin, cycle, or memory setting is out of range"
        )

    previous_tmp = os.environ.get("TMPDIR")
    with tempfile.TemporaryDirectory(prefix="caddsuite-pyscf-") as scratch:
        os.environ["TMPDIR"] = scratch
        try:
            try:
                import numpy as np

                pyscf = importlib.import_module("pyscf")
                pyscf_dft = importlib.import_module("pyscf.dft")
                pyscf_gto = importlib.import_module("pyscf.gto")
                pyscf_scf = importlib.import_module("pyscf.scf")
                pyscf_lib = importlib.import_module("pyscf.lib")
                pyscf_lib.num_threads(n_threads)
            except ImportError as exc:
                raise WorkerFailure(
                    "PYSCF.DEPENDENCY_MISSING", "PySCF and NumPy are required"
                ) from exc
            reporter.emit("progress", "building molecular system", {"engine": "PySCF"})
            mol = pyscf_gto.M(
                atom="\n".join(raw_geometry.splitlines()[1:-1]),
                basis=basis,
                charge=charge,
                spin=multiplicity - 1,
                unit="Angstrom",
                max_memory=memory_mb,
                verbose=0,
            )
            if method.casefold() == "hf":
                mean_field = pyscf_scf.RHF(mol) if multiplicity == 1 else pyscf_scf.UHF(mol)
            else:
                mean_field = pyscf_dft.RKS(mol) if multiplicity == 1 else pyscf_dft.UKS(mol)
                mean_field.xc = method
            mean_field.max_cycle = max_cycle
            mean_field.conv_tol = 1e-10
            mean_field.verbose = 0
            reporter.emit(
                "progress", "running self-consistent field", {"method": method, "basis": basis}
            )
            energy = float(mean_field.kernel())
            converged = bool(mean_field.converged)
            if not converged or not math.isfinite(energy):
                raise WorkerFailure("PYSCF.SCF.NONCONVERGENCE", "PySCF SCF did not converge")
            orbital_blocks = mean_field.mo_energy
            occupation_blocks = mean_field.mo_occ
            if isinstance(orbital_blocks, np.ndarray) and orbital_blocks.ndim == 1:
                orbital_blocks = [orbital_blocks]
                occupation_blocks = [occupation_blocks]
            occupied: list[float] = []
            virtual: list[float] = []
            for orbital_energies, occupations in zip(
                orbital_blocks, occupation_blocks, strict=True
            ):
                occupied.extend(
                    float(value)
                    for value, occ in zip(orbital_energies, occupations, strict=True)
                    if occ > 0
                )
                virtual.extend(
                    float(value)
                    for value, occ in zip(orbital_energies, occupations, strict=True)
                    if occ == 0
                )
            if not occupied or not virtual:
                raise WorkerFailure(
                    "PYSCF.ORBITALS_UNAVAILABLE", "PySCF did not return HOMO and LUMO"
                )
            hartree_to_ev = float(payload["hartree_to_ev"])
            if not math.isfinite(hartree_to_ev) or hartree_to_ev <= 0:
                raise WorkerFailure(
                    "PYSCF.REQUEST_INVALID", "Hartree-to-eV conversion must be positive and finite"
                )
            homo = max(occupied) * hartree_to_ev
            lumo = min(virtual) * hartree_to_ev
            gap = lumo - homo
            dipole_vector = mean_field.dip_moment(unit="Debye", verbose=0)
            dipole = float(np.linalg.norm(dipole_vector))
            coords = mol.atom_coords(unit="Angstrom")
            xyz_lines = [str(mol.natm), "PySCF final single-point geometry in Angstrom"]
            for index, coordinate in enumerate(coords):
                symbol = mol.atom_symbol(index)
                xyz_lines.append(
                    f"{symbol} {coordinate[0]:.12f} {coordinate[1]:.12f} {coordinate[2]:.12f}"
                )
            geometry_path = workdir / "pyscf_final_geometry.xyz"
            with geometry_path.open("x", encoding="utf-8") as stream:
                stream.write("\n".join(xyz_lines) + "\n")
        except WorkerFailure:
            raise
        except Exception as exc:
            raise WorkerFailure(
                "PYSCF.CALCULATION_FAILED", f"PySCF calculation failed: {exc}"
            ) from exc
        finally:
            if previous_tmp is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = previous_tmp
    return {
        "engine": "PySCF",
        "engine_version": str(pyscf.__version__),
        "energy_Eh": energy,
        "scf_converged": converged,
        "homo_eV": homo,
        "lumo_eV": lumo,
        "gap_eV": gap,
        "dipole_D": dipole,
        "atom_count": int(mol.natm),
        "geometry_file": geometry_path.name,
        "parameters": {
            "method": method,
            "basis": basis,
            "charge": charge,
            "multiplicity": multiplicity,
            "max_cycle": max_cycle,
            "memory_mb": memory_mb,
            "n_threads": n_threads,
            "conv_tol_Eh": 1e-10,
            "solvent": None,
            "protocol": "single_point",
        },
    }


def _main() -> int:
    return main(_run, "qm.pyscf.run")


if __name__ == "__main__":
    sys.exit(_main())
