"""Isolated OpenMM worker for native-Amber minimization, NVT, and production stages.

The worker intentionally depends only on the Python standard library and user-installed OpenMM.
It exchanges primitive CLI arguments and a JSON result, never importing the platform package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _input(root: Path, relative: str, expected_hash: str) -> Path:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or "\\" in relative
        or path.as_posix() != relative
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"input path is not a confined canonical relative path: {relative!r}")
    resolved = root.joinpath(*path.parts).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"input path escapes the worker directory or is not a file: {relative!r}")
    actual_hash = _sha256(resolved)
    if actual_hash != expected_hash:
        raise ValueError(f"SHA-256 mismatch for input {relative!r}")
    return resolved


def _output(root: Path, prefix: str, extension: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", prefix) or prefix in {".", ".."}:
        raise ValueError("output prefix is not a safe filename stem")
    path = root / f"{prefix}.{extension}"
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite output {path.name!r}")
    return path


def _run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path.cwd().resolve(strict=True)
    topology_path = _input(root, args.topology, args.topology_sha256)
    coordinates_path = _input(root, args.coordinates, args.coordinates_sha256)
    pdb_path = _output(root, args.output_prefix, "pdb")
    result_path = _output(root, args.output_prefix, "result.json")
    if args.steps < 1:
        raise ValueError("steps/maximum iterations must be positive")
    if args.stage_kind in {"nvt", "production"}:
        dcd_path = _output(root, args.output_prefix, "dcd")
        csv_path = _output(root, args.output_prefix, "csv")
        if args.report_interval_steps < 1:
            raise ValueError("production report interval must be positive")
    if args.random_seed < 0 or args.random_seed > 2**31 - 2:
        raise ValueError("random seed must be within [0, 2^31-2]")

    openmm = import_module("openmm")
    app = import_module("openmm.app")
    unit = import_module("openmm.unit")

    started_at = datetime.now(UTC)
    timer = time.perf_counter()
    topology = app.AmberPrmtopFile(str(topology_path))
    if coordinates_path.suffix.casefold() == ".pdb":
        coordinates = app.PDBFile(str(coordinates_path))
        topology_atoms = tuple(topology.topology.atoms())
        coordinate_atoms = tuple(coordinates.topology.atoms())
        topology_identity = tuple(
            (atom.name, atom.residue.name, atom.residue.id) for atom in topology_atoms
        )
        coordinate_identity = tuple(
            (atom.name, atom.residue.name, atom.residue.id) for atom in coordinate_atoms
        )
        if topology_identity != coordinate_identity:
            raise ValueError("PDB coordinate atom/residue order does not match Amber topology")
        coordinate_box = coordinates.topology.getPeriodicBoxVectors()
        if coordinate_box is not None:
            topology.topology.setPeriodicBoxVectors(coordinate_box)
    elif coordinates_path.suffix.casefold() == ".inpcrd":
        coordinates = app.AmberInpcrdFile(str(coordinates_path))
    else:
        raise ValueError("coordinates must be Amber inpcrd or a topology-matched PDB")
    atom_count = sum(1 for _ in topology.topology.atoms())
    if len(coordinates.positions) != atom_count:
        raise ValueError(
            f"Amber topology has {atom_count} atoms but coordinate file has "
            f"{len(coordinates.positions)} positions"
        )
    box_vectors = getattr(coordinates, "boxVectors", None)
    if box_vectors is None:
        box_vectors = topology.topology.getPeriodicBoxVectors()
    if box_vectors is None:
        raise ValueError("periodic PME stage requires periodic box vectors in Amber coordinates")
    system = topology.createSystem(
        nonbondedMethod=app.PME,
        nonbondedCutoff=args.cutoff_nm * unit.nanometer,
        constraints=app.HBonds,
        rigidWater=True,
        ewaldErrorTolerance=args.ewald_error_tolerance,
    )
    system.setDefaultPeriodicBoxVectors(*box_vectors)
    if args.stage_kind == "minimization":
        integrator = openmm.VerletIntegrator(1.0 * unit.femtoseconds)
    elif args.stage_kind in {"nvt", "production"}:
        integrator = openmm.LangevinMiddleIntegrator(
            args.temperature_k * unit.kelvin,
            args.friction_per_ps / unit.picosecond,
            args.timestep_fs * unit.femtoseconds,
        )
        integrator.setRandomNumberSeed(args.random_seed)
    else:
        raise ValueError(f"unsupported OpenMM stage kind: {args.stage_kind!r}")
    platform = openmm.Platform.getPlatformByName(args.platform)
    properties = {"Threads": str(args.cpu_threads)} if args.platform == "CPU" else {}
    simulation = app.Simulation(topology.topology, system, integrator, platform, properties)
    simulation.context.setPositions(coordinates.positions)
    initial_potential_kcal = (
        simulation.context.getState(getEnergy=True)
        .getPotentialEnergy()
        .value_in_unit(unit.kilocalories_per_mole)
    )
    if args.stage_kind == "minimization":
        simulation.minimizeEnergy(maxIterations=args.steps)
    else:
        simulation.context.setVelocitiesToTemperature(
            args.temperature_k * unit.kelvin,
            args.random_seed + 1,
        )
        simulation.reporters.append(app.DCDReporter(str(dcd_path), args.report_interval_steps))
        simulation.reporters.append(
            app.StateDataReporter(
                str(csv_path),
                args.report_interval_steps,
                step=True,
                time=True,
                temperature=True,
                potentialEnergy=True,
                totalEnergy=True,
                separator=",",
            )
        )

    completed = 0
    if args.stage_kind in {"nvt", "production"}:
        while completed < args.steps:
            count = min(args.report_interval_steps, args.steps - completed)
            simulation.step(count)
            completed += count
            print(f"CADD_PROGRESS {completed}/{args.steps}", flush=True)

    state = simulation.context.getState(getPositions=True, getEnergy=True)
    with pdb_path.open("x", encoding="ascii", newline="\n") as stream:
        app.PDBFile.writeFile(topology.topology, state.getPositions(), stream, keepIds=True)
    potential_kcal_mol = state.getPotentialEnergy().value_in_unit(unit.kilocalories_per_mole)
    if args.stage_kind == "minimization" and potential_kcal_mol > initial_potential_kcal + 1e-5:
        raise ValueError(
            "OpenMM minimization increased potential energy beyond numerical tolerance: "
            f"{initial_potential_kcal:.8f} -> {potential_kcal_mol:.8f} kcal/mol"
        )
    finished_at = datetime.now(UTC)
    if args.stage_kind == "minimization":
        output_hashes = {pdb_path.name: _sha256(pdb_path)}
    else:
        output_hashes = {path.name: _sha256(path) for path in (dcd_path, pdb_path, csv_path)}
    result: dict[str, Any] = {
        "protocol": "caddsuite.openmm-md-worker/1",
        "status": "completed",
        "software": {"name": "OpenMM", "version": openmm.__version__},
        "platform": platform.getName(),
        "atom_count": atom_count,
        "potential_energy_kcal_mol": float(potential_kcal_mol),
        "initial_potential_energy_kcal_mol": float(initial_potential_kcal),
        "input_sha256": {
            "topology": args.topology_sha256,
            "coordinates": args.coordinates_sha256,
        },
        "parameters": {
            "stage_kind": args.stage_kind,
            "constraints": "HBonds",
            "hydrogen_mass_repartitioning": False,
            "nonbonded_method": "PME",
            "cutoff_nm": args.cutoff_nm,
            "ewald_error_tolerance": args.ewald_error_tolerance,
            "cpu_threads": args.cpu_threads,
        },
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "runtime_seconds": time.perf_counter() - timer,
        "outputs": output_hashes,
        "limitations": [
            "Minimization is not equilibration or production dynamics."
            if args.stage_kind == "minimization"
            else (
                "Short NVT equilibration smoke; not a stability or production validation."
                if args.stage_kind == "nvt"
                else "Short adapter execution check; not a production MD validation or "
                "binding-stability result."
            )
        ],
    }
    if args.stage_kind == "minimization":
        result["maximum_iterations"] = args.steps
        result["potential_energy_change_kcal_mol"] = float(
            potential_kcal_mol - initial_potential_kcal
        )
        result["outputs"] = output_hashes
    else:
        result["steps_completed"] = completed
        result["time_ps"] = completed * args.timestep_fs / 1000.0
        result["parameters"].update(
            {
                "integrator": "OpenMM LangevinMiddleIntegrator",
                "temperature_K": args.temperature_k,
                "friction_per_ps": args.friction_per_ps,
                "timestep_fs": args.timestep_fs,
                "steps": args.steps,
                "random_seed": args.random_seed,
                "report_interval_steps": args.report_interval_steps,
            }
        )
        result["outputs"] = output_hashes
    temporary = result_path.with_suffix(".json.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", required=True)
    parser.add_argument("--coordinates", required=True)
    parser.add_argument("--topology-sha256", required=True)
    parser.add_argument("--coordinates-sha256", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument(
        "--stage-kind", choices=("minimization", "nvt", "production"), required=True
    )
    parser.add_argument("--timestep-fs", type=float, default=2.0)
    parser.add_argument("--temperature-k", type=float, default=303.15)
    parser.add_argument("--friction-per-ps", type=float, default=1.0)
    parser.add_argument("--cutoff-nm", type=float, required=True)
    parser.add_argument("--ewald-error-tolerance", type=float, required=True)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--report-interval-steps", type=int, default=100)
    parser.add_argument("--cpu-threads", type=int, required=True)
    parser.add_argument("--platform", choices=("CPU", "Reference"), required=True)
    args = parser.parse_args()
    try:
        result = _run(args)
    except Exception as exc:  # worker boundary must return an actionable process error
        print(f"OpenMM stage failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "stage_kind": result["parameters"]["stage_kind"],
                "steps_completed": result.get("steps_completed"),
                "maximum_iterations": result.get("maximum_iterations"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
