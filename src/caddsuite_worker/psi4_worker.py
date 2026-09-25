"""Fresh-process worker for the migrated molecular Psi4 recipe."""

from __future__ import annotations

import importlib.util
import math
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from caddsuite_worker.runtime import EventReporter, WorkerFailure, main

_ELEMENTS = {
    "H": 1,
    "He": 2,
    "Li": 3,
    "Be": 4,
    "B": 5,
    "C": 6,
    "N": 7,
    "O": 8,
    "F": 9,
    "Ne": 10,
    "Na": 11,
    "Mg": 12,
    "Al": 13,
    "Si": 14,
    "P": 15,
    "S": 16,
    "Cl": 17,
    "Ar": 18,
    "K": 19,
    "Ca": 20,
    "Sc": 21,
    "Ti": 22,
    "V": 23,
    "Cr": 24,
    "Mn": 25,
    "Fe": 26,
    "Co": 27,
    "Ni": 28,
    "Cu": 29,
    "Zn": 30,
    "Ga": 31,
    "Ge": 32,
    "As": 33,
    "Se": 34,
    "Br": 35,
    "Kr": 36,
    "Rb": 37,
    "Sr": 38,
    "Y": 39,
    "Zr": 40,
    "Nb": 41,
    "Mo": 42,
    "Tc": 43,
    "Ru": 44,
    "Rh": 45,
    "Pd": 46,
    "Ag": 47,
    "Cd": 48,
    "In": 49,
    "Sn": 50,
    "Sb": 51,
    "Te": 52,
    "I": 53,
    "Xe": 54,
    "Cs": 55,
    "Ba": 56,
    "La": 57,
    "Ce": 58,
    "Pr": 59,
    "Nd": 60,
    "Pm": 61,
    "Sm": 62,
    "Eu": 63,
    "Gd": 64,
    "Tb": 65,
    "Dy": 66,
    "Ho": 67,
    "Er": 68,
    "Tm": 69,
    "Yb": 70,
    "Lu": 71,
    "Hf": 72,
    "Ta": 73,
    "W": 74,
    "Re": 75,
    "Os": 76,
    "Ir": 77,
    "Pt": 78,
    "Au": 79,
    "Hg": 80,
    "Tl": 81,
    "Pb": 82,
    "Bi": 83,
    "Po": 84,
    "At": 85,
    "Rn": 86,
    "Fr": 87,
    "Ra": 88,
    "Ac": 89,
    "Th": 90,
    "Pa": 91,
    "U": 92,
    "Np": 93,
    "Pu": 94,
    "Am": 95,
    "Cm": 96,
    "Bk": 97,
    "Cf": 98,
    "Es": 99,
    "Fm": 100,
    "Md": 101,
    "No": 102,
    "Lr": 103,
    "Rf": 104,
    "Db": 105,
    "Sg": 106,
    "Bh": 107,
    "Hs": 108,
    "Mt": 109,
    "Ds": 110,
    "Rg": 111,
    "Cn": 112,
    "Nh": 113,
    "Fl": 114,
    "Mc": 115,
    "Lv": 116,
    "Ts": 117,
    "Og": 118,
}
_METHOD_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+*/().-]{0,127}$")
_SOLVENTS = {
    "none",
    "water",
    "methanol",
    "ethanol",
    "acetone",
    "dmso",
    "chloroform",
    "toluene",
    "thf",
    "acetonitrile",
}
_PROTOCOLS = {
    "single_point": "energy",
    "optimization": "optimize",
    "frequency": "frequency",
    "opt_freq": "opt_freq",
    "tddft": "energy",
}


def _integer(payload: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise WorkerFailure(
            "PSI4.INPUT.INVALID",
            key + " must be an integer in [" + str(minimum) + ", " + str(maximum) + "]",
        )
    return value


def _geometry_and_electrons(payload: dict[str, Any]) -> tuple[str, int]:
    raw = payload.get("geometry_block")
    charge = _integer(payload, "charge", -100, 100)
    multiplicity = _integer(payload, "multiplicity", 1, 100)
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 1_000_000:
        raise WorkerFailure("PSI4.INPUT.INVALID", "geometry_block must be non-empty text <=1 MB")

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise WorkerFailure("PSI4.INPUT.INVALID", "geometry has no atom coordinates")
    header = lines[0].split()
    if len(header) != 2:
        raise WorkerFailure(
            "PSI4.INPUT.INVALID",
            "geometry must start with explicit charge and multiplicity",
        )
    try:
        header_charge, header_multiplicity = (int(part) for part in header)
    except ValueError as exc:
        raise WorkerFailure("PSI4.INPUT.INVALID", "geometry charge/spin header is invalid") from exc
    if (header_charge, header_multiplicity) != (charge, multiplicity):
        raise WorkerFailure(
            "PSI4.INPUT.INVALID",
            "geometry header charge/multiplicity differs from the task parameters",
        )

    atom_rows = []
    electron_count = -charge
    units_seen = False
    for line in lines[1:]:
        tokens = line.split()
        if [token.casefold() for token in tokens] == ["units", "angstrom"]:
            if units_seen:
                raise WorkerFailure("PSI4.INPUT.INVALID", "geometry repeats the units directive")
            units_seen = True
            continue
        if len(tokens) != 4 or tokens[0] not in _ELEMENTS:
            raise WorkerFailure(
                "PSI4.INPUT.INVALID",
                "geometry accepts only element x y z rows and an optional units angstrom line",
            )
        try:
            coordinates = [float(item) for item in tokens[1:]]
        except ValueError as exc:
            raise WorkerFailure(
                "PSI4.INPUT.INVALID", "geometry has a non-numeric coordinate"
            ) from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise WorkerFailure("PSI4.INPUT.INVALID", "geometry coordinates must be finite")
        atom_rows.append(line)
        electron_count += _ELEMENTS[tokens[0]]
    if not atom_rows or len(atom_rows) > 2000:
        raise WorkerFailure("PSI4.INPUT.INVALID", "geometry must contain 1 to 2000 atoms")
    if electron_count < multiplicity - 1 or (electron_count - (multiplicity - 1)) % 2:
        raise WorkerFailure(
            "PSI4.SPIN.PARITY",
            "electron count is inconsistent with the requested spin multiplicity",
        )

    normalized = [str(charge) + " " + str(multiplicity), *atom_rows, "units angstrom"]
    return "\n".join(normalized), len(atom_rows)


def _resolve_fukui_spins(
    electron_count: int,
    neutral_multiplicity: int,
    selection: dict[str, Any],
) -> dict[str, Any]:
    """Worker-local validation keeps this process independent of the platform core."""
    anion = selection.get("anion_multiplicity")
    cation = selection.get("cation_multiplicity")
    if neutral_multiplicity == 1:
        explicit_selection = anion is not None or cation is not None
        anion = 2 if anion is None else anion
        cation = 2 if cation is None else cation
        policy = (
            "explicit_user_multiplicities"
            if explicit_selection
            else "closed_shell_frontier_doublet"
        )
    else:
        if anion is None or cation is None:
            raise ValueError(
                "open-shell neutral Fukui calculations require explicit anion and cation "
                "multiplicities"
            )
        policy = "explicit_user_multiplicities"
    for state, electrons, multiplicity in (
        ("anion (N+1)", electron_count + 1, anion),
        ("cation (N-1)", electron_count - 1, cation),
    ):
        if (
            isinstance(multiplicity, bool)
            or not isinstance(multiplicity, int)
            or multiplicity < 1
            or electrons < multiplicity - 1
            or (electrons - multiplicity + 1) % 2
        ):
            raise ValueError(f"{state} electron count and multiplicity are incompatible")
    return {
        "anion_multiplicity": anion,
        "cation_multiplicity": cation,
        "selection_policy": policy,
    }


def _configuration(payload: dict[str, Any]) -> dict[str, Any]:
    protocol = payload.get("protocol")
    if protocol not in _PROTOCOLS:
        raise WorkerFailure("PSI4.CAPABILITY.UNSUPPORTED", "unsupported Psi4 calculation protocol")
    method = payload.get("method")
    basis = payload.get("basis")
    if not isinstance(method, str) or not _METHOD_TOKEN.fullmatch(method):
        raise WorkerFailure("PSI4.INPUT.INVALID", "method label is malformed")
    if not isinstance(basis, str) or not _METHOD_TOKEN.fullmatch(basis):
        raise WorkerFailure("PSI4.INPUT.INVALID", "basis label is malformed")
    solvent = payload.get("solvent", "none")
    if not isinstance(solvent, str) or solvent.casefold() not in _SOLVENTS:
        raise WorkerFailure("PSI4.CAPABILITY.UNSUPPORTED", "solvent is not in the audited Psi4 set")
    solvent = solvent.casefold()

    n_excited_states = _integer(payload, "n_excited_states", 0, 100)
    if protocol == "tddft" and n_excited_states < 1:
        raise WorkerFailure("PSI4.INPUT.INVALID", "TD-DFT requires at least one excited state")
    if protocol != "tddft" and n_excited_states:
        raise WorkerFailure(
            "PSI4.INPUT.INVALID", "excited-state count requires the TD-DFT protocol"
        )

    for flag in ("compute_charges", "compute_resp_charges"):
        if not isinstance(payload.get(flag, False), bool):
            raise WorkerFailure("PSI4.INPUT.INVALID", flag + " must be true or false")
    products = payload.get("volumetric_products", [])
    if (
        not isinstance(products, list)
        or any(item not in {"frontier_orbitals", "mep", "fukui"} for item in products)
        or len(set(products)) != len(products)
    ):
        raise WorkerFailure("PSI4.INPUT.INVALID", "volumetric_products contains invalid entries")
    spacing_angstrom = payload.get("cube_grid_spacing_angstrom", 0.25)
    spacing_bohr = payload.get("cube_grid_spacing_bohr")
    if not products and spacing_bohr is None:
        spacing_bohr = 0.25 * 1.8897261254578281
    grid_overage = payload.get("cube_grid_overage_bohr", 4.0)
    if (
        isinstance(grid_overage, bool)
        or not isinstance(grid_overage, (int, float))
        or not math.isfinite(grid_overage)
        or not 0.0 < grid_overage <= 20.0
    ):
        raise WorkerFailure("PSI4.INPUT.INVALID", "cube_grid_overage_bohr must be in (0, 20]")
    if payload.get("generate_figures", False) or payload.get("compute_fukui", False):
        raise WorkerFailure(
            "PSI4.CAPABILITY.UNSUPPORTED",
            "use explicit volumetric_products instead of legacy figure flags",
        )
    if (
        isinstance(spacing_angstrom, bool)
        or not isinstance(spacing_angstrom, (int, float))
        or not math.isfinite(spacing_angstrom)
        or not 0.05 < spacing_angstrom <= 1.0
        or isinstance(spacing_bohr, bool)
        or not isinstance(spacing_bohr, (int, float))
        or not math.isfinite(spacing_bohr)
        or spacing_bohr <= 0
    ):
        raise WorkerFailure("PSI4.INPUT.INVALID", "cube spacing values must be finite and positive")
    df_basis_scf = payload.get("df_basis_scf")
    if "mep" in products and (
        not isinstance(df_basis_scf, str) or not _METHOD_TOKEN.fullmatch(df_basis_scf)
    ):
        raise WorkerFailure("PSI4.INPUT.INVALID", "MEP requires a valid explicit df_basis_scf")
    anion_basis = payload.get("fukui_anion_basis")
    if anion_basis is not None and (
        not isinstance(anion_basis, str) or not _METHOD_TOKEN.fullmatch(anion_basis)
    ):
        raise WorkerFailure("PSI4.INPUT.INVALID", "fukui_anion_basis is malformed")
    spin_states = payload.get("fukui_spin_states")
    if spin_states is not None and (
        not isinstance(spin_states, dict)
        or set(spin_states) - {"anion_multiplicity", "cation_multiplicity"}
    ):
        raise WorkerFailure("PSI4.INPUT.INVALID", "fukui_spin_states is malformed")
    if "fukui" in products:
        geometry_for_electrons, _ = _geometry_and_electrons(payload)
        electron_count = (
            sum(
                _ELEMENTS[row.split()[0]]
                for row in geometry_for_electrons.splitlines()[1:]
                if len(row.split()) == 4
            )
            - payload["charge"]
        )
        selection = spin_states if isinstance(spin_states, dict) else {}
        try:
            resolved = _resolve_fukui_spins(
                electron_count,
                payload["multiplicity"],
                selection,
            )
        except (TypeError, ValueError) as exc:
            raise WorkerFailure("PSI4.SPIN.INVALID", str(exc)) from exc
        spin_states = resolved
    pose_path = payload.get("docked_pose_path")
    expected_smiles = payload.get("expected_smiles")
    pose_id = payload.get("pose_id")
    pose_identity_verified = False
    pose_heavy_atom_count = None
    if pose_path is not None:
        if (
            not isinstance(pose_path, str)
            or not isinstance(expected_smiles, str)
            or not expected_smiles
        ):
            raise WorkerFailure(
                "PSI4.INPUT.INVALID", "pose analysis requires a staged SDF and form SMILES"
            )
        relative = PurePosixPath(pose_path)
        if (
            relative.is_absolute()
            or "\\" in pose_path
            or ".." in relative.parts
            or relative.suffix.casefold() != ".sdf"
        ):
            raise WorkerFailure("PSI4.INPUT.INVALID", "pose path must be a confined normalized SDF")
        root = Path.cwd().resolve(strict=True)
        try:
            source = (root / Path(*relative.parts)).resolve(strict=True)
        except OSError as exc:
            raise WorkerFailure("PSI4.INPUT.INVALID", "staged pose SDF is unavailable") from exc
        if not source.is_relative_to(root) or not source.is_file():
            raise WorkerFailure("PSI4.INPUT.INVALID", "staged pose SDF escapes the task directory")
        if not isinstance(pose_id, str) or not pose_id:
            raise WorkerFailure(
                "PSI4.INPUT.INVALID", "pose analysis requires its registered pose ID"
            )
        from .pose_analysis import load_docked_pose

        try:
            pose = load_docked_pose(
                str(source), expected_smiles, payload["charge"], payload["multiplicity"]
            )
        except (ValueError, OSError) as exc:
            raise WorkerFailure("PSI4.POSE.IDENTITY_MISMATCH", str(exc)) from exc
        geometry, _ = _geometry_and_electrons(payload)
        pose_geometry, atom_count = _geometry_and_electrons(
            {
                "geometry_block": pose["geometry_block"],
                "charge": payload["charge"],
                "multiplicity": payload["multiplicity"],
            }
        )
        if geometry != pose_geometry:
            raise WorkerFailure(
                "PSI4.POSE.GEOMETRY_MISMATCH",
                "task geometry differs from the hash-verified normalized pose artifact",
            )
        if payload.get("protocol") not in {"optimization", "opt_freq"}:
            raise WorkerFailure(
                "PSI4.CAPABILITY.UNSUPPORTED",
                "pose strain requires an optimization protocol",
            )
        pose_identity_verified = True
        pose_heavy_atom_count = len(pose["atom_map_form_to_pose"])
    elif expected_smiles is not None or pose_id is not None:
        raise WorkerFailure("PSI4.INPUT.INVALID", "pose metadata requires docked_pose_path")
    keywords = payload.get("keywords", {})
    if keywords:
        raise WorkerFailure(
            "PSI4.CAPABILITY.UNSUPPORTED",
            "arbitrary Psi4 keyword overrides are not accepted by this worker",
        )

    geometry, atom_count = _geometry_and_electrons(payload)
    charge = payload["charge"]
    multiplicity = payload["multiplicity"]
    return {
        "geometry_block": geometry,
        "functional": method,
        "basis": basis,
        "calc_type": _PROTOCOLS[protocol],
        "charge": charge,
        "multiplicity": multiplicity,
        "memory_gb": _integer(payload, "memory_gb", 1, 256),
        "n_threads": _integer(payload, "n_threads", 1, 256),
        "job_name": "psi4_calculation",
        "output_dir": ".",
        "n_conformers": 1,
        "solvent": solvent,
        "n_excited_states": n_excited_states,
        "compute_charges": payload.get("compute_charges", False),
        "compute_resp_charges": payload.get("compute_resp_charges", False),
        "volumetric_products": products,
        "cube_grid_spacing_angstrom": float(spacing_angstrom),
        "cube_grid_spacing_bohr": float(spacing_bohr),
        "cube_grid_overage_bohr": float(grid_overage),
        "df_basis_scf": df_basis_scf,
        "fukui_spin_states": spin_states,
        "fukui_anion_basis": anion_basis,
        "generate_figures": False,
        "figure_quality": "standard",
        "keep_cubes": False,
        "docked_pose_path": str(source.relative_to(Path.cwd().resolve()))
        if pose_path is not None
        else None,
        "expected_smiles": expected_smiles if pose_path is not None else None,
        "compute_fukui": False,
        "pose_identity_verified": pose_identity_verified,
        "pose_id": pose_id if pose_path is not None else None,
        "pose_heavy_atom_count": pose_heavy_atom_count,
        "atom_count": atom_count,
    }


def _run(request: dict[str, Any], reporter: EventReporter) -> dict[str, Any]:
    payload = request["payload"]
    if not isinstance(payload, dict):
        raise WorkerFailure("PSI4.INPUT.INVALID", "Psi4 payload must be an object")
    config = _configuration(payload)
    atom_count = config.pop("atom_count")
    pose_identity_verified = config.pop("pose_identity_verified")
    pose_id = config.pop("pose_id")
    pose_heavy_atom_count = config.pop("pose_heavy_atom_count")
    raw_output = Path.cwd() / "psi4_calculation.psi4.out"
    legacy_result = Path.cwd() / "psi4_calculation.result.json"
    final_geometry = Path.cwd() / "psi4_calculation.final_geometry.xyz"
    if (
        raw_output.exists()
        or raw_output.is_symlink()
        or legacy_result.exists()
        or legacy_result.is_symlink()
        or final_geometry.exists()
        or final_geometry.is_symlink()
    ):
        raise WorkerFailure(
            "PSI4.OUTPUT.EXISTS",
            "Psi4 worker refuses to overwrite an existing raw output",
        )

    with tempfile.TemporaryDirectory(prefix=".psi4-scratch-", dir=str(Path.cwd())) as scratch:
        previous_scratch = os.environ.get("PSI_SCRATCH")
        os.environ["PSI_SCRATCH"] = scratch
        try:
            import psi4  # type: ignore[import-not-found]

            from .psi4_engine import DFTJobConfig, run_dft_job

            if config["solvent"] != "none" and importlib.util.find_spec("pyddx") is None:
                raise WorkerFailure(
                    "PSI4.CAPABILITY.UNSUPPORTED",
                    "implicit solvation requires the pyddx package in the Psi4 environment",
                )
            if config["compute_resp_charges"] and importlib.util.find_spec("resp") is None:
                raise WorkerFailure(
                    "PSI4.CAPABILITY.UNSUPPORTED",
                    "RESP charge analysis requires the resp package in the Psi4 environment",
                )
            reporter.emit(
                "log",
                "starting isolated Psi4 job",
                {
                    "engine_version": str(psi4.__version__),
                    "protocol": str(payload["protocol"]),
                    "atoms": atom_count,
                    "scratch_isolation": "private temporary directory; cleaned on exit",
                },
            )
            job = DFTJobConfig(**config)
            log_messages: list[str] = []

            def log(message: str) -> None:
                log_messages.append(message[:4096])
                reporter.emit("log", message[:4096])

            result = run_dft_job(job, log_callback=log)
        except WorkerFailure:
            raise
        except Exception as exc:
            raise WorkerFailure(
                "PSI4.ENGINE.FAILURE",
                "Psi4 could not initialize or execute: " + str(exc),
            ) from exc
        finally:
            if previous_scratch is None:
                os.environ.pop("PSI_SCRATCH", None)
            else:
                os.environ["PSI_SCRATCH"] = previous_scratch

    if not result.success:
        error = result.error or "Psi4 calculation returned success=false without an error message"
        lowered = error.casefold()
        if "scf" in lowered and ("converg" in lowered or "iteration" in lowered):
            code = "PSI4.SCF.NONCONVERGENCE"
        elif "optimization" in lowered and "converg" in lowered:
            code = "PSI4.OPTIMIZATION.NONCONVERGENCE"
        else:
            code = "PSI4.CALCULATION.FAILED"
        raise WorkerFailure(code, error, retryable=False)

    result_data = result.__dict__.copy()
    if not isinstance(result.final_geometry, str) or not result.final_geometry.strip():
        raise WorkerFailure(
            "PSI4.RESULT.GEOMETRY_MISSING",
            "Psi4 calculation returned no final geometry",
        )
    final_geometry.write_text(result.final_geometry.rstrip() + "\n", encoding="utf-8")
    return {
        "engine": "Psi4",
        "engine_version": str(psi4.__version__),
        "atom_count": atom_count,
        "parameters": {
            "functional": config["functional"],
            "basis": config["basis"],
            "calculation_type": config["calc_type"],
            "charge": config["charge"],
            "multiplicity": config["multiplicity"],
            "memory_gb": config["memory_gb"],
            "n_threads": config["n_threads"],
            "solvent": config["solvent"],
            "n_excited_states": config["n_excited_states"],
            "compute_charges": config["compute_charges"],
            "compute_resp_charges": config["compute_resp_charges"],
            "volumetric_products": config["volumetric_products"],
            "cube_grid_spacing_angstrom": config["cube_grid_spacing_angstrom"],
            "cube_grid_spacing_bohr": config["cube_grid_spacing_bohr"],
            "df_basis_scf": config["df_basis_scf"],
            "fukui_spin_states": config["fukui_spin_states"],
        },
        "volumetric_files": result_data.get("volumetric_files", {}),
        "volumetric_failures": result_data.get("volumetric_failures", {}),
        "volumetric_metadata": {
            "engine": "Psi4",
            "engine_version": str(psi4.__version__),
            "method": config["functional"],
            "basis": config["basis"],
            "charge": config["charge"],
            "multiplicity": config["multiplicity"],
            "requested_products": config["volumetric_products"],
            "grid_spacing_angstrom": config["cube_grid_spacing_angstrom"],
            "grid_spacing_bohr": config["cube_grid_spacing_bohr"],
            "grid_overage_bohr": config["cube_grid_overage_bohr"],
            "density_fitting_basis": config["df_basis_scf"],
            "charge_state_details": result_data.get("volumetric_metadata", {}),
        },
        "legacy_result": result_data,
        "legacy_warnings": [message for message in log_messages if message.startswith("(")],
        "pose_identity_verified": pose_identity_verified,
        "pose_id": pose_id,
        "pose_heavy_atom_count": pose_heavy_atom_count,
        "raw_output": raw_output.name,
        "legacy_result_file": legacy_result.name,
        "final_geometry_file": final_geometry.name,
    }


def _main() -> int:
    return main(_run, "qm.psi4.run")


if __name__ == "__main__":
    sys.exit(_main())
