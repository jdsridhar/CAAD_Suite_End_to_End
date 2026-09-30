"""Validate a hash-linked single-system PDB/DCD trajectory without modifying coordinates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
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


def _input(root: Path, payload: object, label: str) -> tuple[Path, str]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} record must be an object")
    raw_path, expected_hash = payload.get("path"), payload.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
        raise ValueError(f"{label} path/hash must be strings")
    relative = PurePosixPath(raw_path)
    if (
        not raw_path
        or "\\" in raw_path
        or relative.is_absolute()
        or relative.as_posix() != raw_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"{label} path is not a confined canonical relative path")
    path = root.joinpath(*relative.parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{label} is not a regular file inside the private work directory")
    actual = _sha256(path)
    if actual != expected_hash:
        raise ValueError(f"{label} SHA-256 does not match the request")
    return path, actual


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _run(request_path: Path, output_path: Path) -> dict[str, Any]:
    root = Path.cwd().resolve(strict=True)
    request_path = _confined_control_path(root, request_path, "request")
    output_path = _confined_control_path(root, output_path, "output", allow_missing=True)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if (
        not isinstance(request, dict)
        or request.get("protocol") != "caddsuite.mdanalysis-trajectory/1"
    ):
        raise ValueError("request protocol is invalid")
    topology_path, topology_hash = _input(root, request.get("topology"), "topology")
    trajectory_path, trajectory_hash = _input(root, request.get("trajectory"), "trajectory")
    expected_atoms = request.get("expected_atom_count")
    expected_frames = request.get("expected_frame_count")
    if (
        isinstance(expected_atoms, bool)
        or not isinstance(expected_atoms, int)
        or expected_atoms < 1
        or isinstance(expected_frames, bool)
        or not isinstance(expected_frames, int)
        or expected_frames < 1
    ):
        raise ValueError("expected atom/frame counts must be positive integers")
    if expected_frames < 2:
        raise ValueError("validation requires at least two trajectory frames")

    started = datetime.now(UTC)
    mda = import_module("MDAnalysis")
    numpy = import_module("numpy")
    universe = mda.Universe(str(topology_path), str(trajectory_path))
    if len(universe.atoms) != expected_atoms or len(universe.trajectory) != expected_frames:
        raise ValueError("PDB/DCD atom or frame count differs from the request")
    times: list[float] = []
    final_dimensions: list[float] | None = None
    for timestep in universe.trajectory:
        time_ps = _finite_number(timestep.time, "frame time")
        positions = numpy.asarray(universe.atoms.positions, dtype=float)
        if positions.shape != (expected_atoms, 3) or not numpy.isfinite(positions).all():
            raise ValueError("trajectory contains invalid atom coordinates")
        dimensions = numpy.asarray(timestep.dimensions, dtype=float)
        if dimensions.shape != (6,) or not numpy.isfinite(dimensions).all():
            raise ValueError("trajectory frame lacks finite periodic box dimensions")
        if numpy.any(dimensions[:3] <= 0) or numpy.any(dimensions[3:] <= 0):
            raise ValueError("trajectory frame has non-positive periodic box dimensions")
        times.append(time_ps)
        final_dimensions = [float(value) for value in dimensions]

    intervals = numpy.diff(numpy.asarray(times, dtype=float))
    declared_first = _finite_number(request.get("output_start_time_ps"), "output start time")
    declared_interval = _finite_number(request.get("frame_interval_ps"), "frame interval")
    if declared_interval <= 0 or numpy.any(intervals <= 0):
        raise ValueError("trajectory frame times or requested interval are non-positive")
    if not numpy.allclose(intervals, declared_interval, rtol=0.0, atol=1e-4):
        raise ValueError("observed DCD time spacing differs from declared frame interval")
    if not math.isclose(times[0], declared_first, rel_tol=0.0, abs_tol=1e-4):
        raise ValueError("observed DCD start time differs from the declared output start")
    expected_span = declared_interval * (expected_frames - 1)
    if not math.isclose(times[-1] - times[0], expected_span, rel_tol=0.0, abs_tol=1e-4):
        raise ValueError("observed DCD time span contradicts frame count and interval")
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite {output_path.name!r}")
    result: dict[str, Any] = {
        "protocol": "caddsuite.mdanalysis-trajectory/1",
        "status": "validated",
        "request_id": request.get("request_id"),
        "simulation_id": request.get("simulation_id"),
        "processor": {"name": "MDAnalysis", "version": str(mda.__version__)},
        "metadata": {
            "topology_sha256": topology_hash,
            "trajectory_sha256": trajectory_hash,
            "n_atoms": len(universe.atoms),
            "n_frames": len(universe.trajectory),
            "first_time_ps": times[0],
            "last_time_ps": times[-1],
            "frame_interval_ps": float(numpy.mean(intervals)),
            "periodic_box_lengths_A_angles_deg": final_dimensions,
            "coordinates_modified": False,
        },
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, output_path)
    return result


def _confined_control_path(
    root: Path, path: Path, label: str, *, allow_missing: bool = False
) -> Path:
    if path.is_absolute():
        raise ValueError(f"{label} path must be relative to the private work directory")
    candidate = root / path
    resolved = candidate.resolve(strict=not allow_missing)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} path escapes the private work directory")
    if allow_missing and (candidate.exists() or candidate.is_symlink()):
        raise FileExistsError(f"refusing existing {label} path")
    if not allow_missing and not resolved.is_file():
        raise ValueError(f"{label} path is not a regular file")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = _run(args.request, args.output)
    except Exception as exc:  # worker boundary returns an actionable failure to the executor
        print(
            f"MDAnalysis trajectory validation failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "n_atoms": result["metadata"]["n_atoms"],
                "n_frames": result["metadata"]["n_frames"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
