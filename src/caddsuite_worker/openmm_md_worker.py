"""Isolated OpenMM worker for short native-Amber MD production stages.

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
    dcd_path = _output(root, args.output_prefix, "dcd")
    pdb_path = _output(root, args.output_prefix, "pdb")
    csv_path = _output(root, args.output_prefix, "csv")
    result_path = _output(root, args.output_prefix, "result.json")
    if args.steps < 1 or args.report_interval_steps < 1:
        raise ValueError("steps and report interval must be positive")
    if args.random_seed < 0 or args.random_seed > 2**31 - 2:
        raise ValueError("random seed must be within [0, 2^31-2]")

    openmm = import_module("openmm")
    app = import_module("openmm.app")
    unit = import_module("openmm.unit")

    started_at = datetime.now(UTC)
    timer = time.perf_counter()
    topology = app.AmberPrmtopFile(str(topology_path))
    coordinates = app.AmberInpcrdFile(str(coordinates_path))
    atom_count = sum(1 for _ in topology.topology.atoms())
    if len(coordinates.positions) != atom_count:
        raise ValueError(
            f"Amber topology has {atom_count} atoms but coordinate file has "
            f"{len(coordinates.positions)} positions"
        )
    if coordinates.boxVectors is None:
        raise ValueError("periodic PME stage requires periodic box vectors in Amber coordinates")
    system = topology.createSystem(
        nonbondedMethod=app.PME,
        nonbondedCutoff=args.cutoff_nm * unit.nanometer,
        constraints=app.HBonds,
        rigidWater=True,
        ewaldErrorTolerance=args.ewald_error_tolerance,
    )
    system.setDefaultPeriodicBoxVectors(*coordinates.boxVectors)
    integrator = openmm.LangevinMiddleIntegrator(
        args.temperature_k * unit.kelvin,
        args.friction_per_ps / unit.picosecond,
        args.timestep_fs * unit.femtoseconds,
    )
    integrator.setRandomNumberSeed(args.random_seed)
    platform = openmm.Platform.getPlatformByName(args.platform)
    properties = {"Threads": str(args.cpu_threads)} if args.platform == "CPU" else {}
    simulation = app.Simulation(topology.topology, system, integrator, platform, properties)
    simulation.context.setPositions(coordinates.positions)
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
    while completed < args.steps:
        count = min(args.report_interval_steps, args.steps - completed)
        simulation.step(count)
        completed += count
        print(f"CADD_PROGRESS {completed}/{args.steps}", flush=True)

    state = simulation.context.getState(getPositions=True, getEnergy=True)
    with pdb_path.open("x", encoding="ascii", newline="\n") as stream:
        app.PDBFile.writeFile(topology.topology, state.getPositions(), stream, keepIds=True)
    potential_kcal_mol = state.getPotentialEnergy().value_in_unit(unit.kilocalories_per_mole)
    finished_at = datetime.now(UTC)
    output_hashes = {path.name: _sha256(path) for path in (dcd_path, pdb_path, csv_path)}
    result: dict[str, Any] = {
        "protocol": "caddsuite.openmm-md-worker/1",
        "status": "completed",
        "software": {"name": "OpenMM", "version": openmm.__version__},
        "platform": platform.getName(),
        "atom_count": atom_count,
        "steps_completed": completed,
        "time_ps": completed * args.timestep_fs / 1000.0,
        "potential_energy_kcal_mol": float(potential_kcal_mol),
        "input_sha256": {
            "topology": args.topology_sha256,
            "coordinates": args.coordinates_sha256,
        },
        "parameters": {
            "integrator": "OpenMM LangevinMiddleIntegrator",
            "temperature_K": args.temperature_k,
            "friction_per_ps": args.friction_per_ps,
            "timestep_fs": args.timestep_fs,
            "steps": args.steps,
            "constraints": "HBonds",
            "hydrogen_mass_repartitioning": False,
            "nonbonded_method": "PME",
            "cutoff_nm": args.cutoff_nm,
            "ewald_error_tolerance": args.ewald_error_tolerance,
            "random_seed": args.random_seed,
            "report_interval_steps": args.report_interval_steps,
            "cpu_threads": args.cpu_threads,
        },
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "runtime_seconds": time.perf_counter() - timer,
        "outputs": output_hashes,
        "limitations": [
            "Short adapter execution check; not a production MD validation or "
            "binding-stability result."
        ],
    }
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
    parser.add_argument("--timestep-fs", type=float, required=True)
    parser.add_argument("--temperature-k", type=float, required=True)
    parser.add_argument("--friction-per-ps", type=float, required=True)
    parser.add_argument("--cutoff-nm", type=float, required=True)
    parser.add_argument("--ewald-error-tolerance", type=float, required=True)
    parser.add_argument("--random-seed", type=int, required=True)
    parser.add_argument("--report-interval-steps", type=int, required=True)
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
            {"status": result["status"], "steps_completed": result["steps_completed"]},
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
