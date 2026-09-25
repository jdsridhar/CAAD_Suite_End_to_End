"""Probe stable MDAnalysis support for one staged GROMACS TPR/GRO/XTC bundle.

Run this worker in the optional analysis environment. It emits JSON on stdout and writes no result
files. Any XTC offset cache is created only beside the caller's staged input copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import import_module
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any


def _input(root: Path, relative: str) -> Path:
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
        raise ValueError(f"input is outside the private stage or is not a file: {relative!r}")
    return resolved


def _probe(args: argparse.Namespace) -> dict[str, Any]:
    root = Path.cwd().resolve(strict=True)
    tpr = _input(root, args.tpr)
    gro = _input(root, args.gro)
    xtc = _input(root, args.xtc)
    mda = import_module("MDAnalysis")
    tpr_status: dict[str, str] = {"status": "accepted", "error": ""}
    try:
        mda.Universe(str(tpr))
    except Exception as exc:  # Report reader compatibility; this is the probe's purpose.
        tpr_status = {"status": "unsupported", "error": f"{type(exc).__name__}: {exc}"}

    universe = mda.Universe(str(gro), str(xtc))
    atom_count = len(universe.atoms)
    frame_count = len(universe.trajectory)
    if atom_count < 1 or frame_count < 1:
        raise ValueError("GRO/XTC fallback produced an empty atom set or trajectory")
    numpy = import_module("numpy")
    times: list[float] = []
    finite_coordinates = True
    finite_dimensions = True
    for timestep in universe.trajectory:
        times.append(float(timestep.time))
        finite_coordinates = finite_coordinates and bool(numpy.isfinite(timestep.positions).all())
        finite_dimensions = finite_dimensions and bool(
            timestep.dimensions is not None and numpy.isfinite(timestep.dimensions).all()
        )
    try:
        bond_count: int | None = len(universe.bonds)
    except Exception:
        bond_count = None
    if not finite_coordinates or not finite_dimensions:
        raise ValueError("GRO/XTC fallback contains non-finite coordinates or box dimensions")
    if any(later <= earlier for earlier, later in pairwise(times)):
        raise ValueError("XTC frame times are not strictly increasing")
    universe.trajectory[0]
    first_dimensions = [float(value) for value in universe.trajectory.ts.dimensions]
    universe.trajectory[-1]
    last_dimensions = [float(value) for value in universe.trajectory.ts.dimensions]
    return {
        "protocol": "caddsuite.mdanalysis-gromacs-probe/1",
        "mdanalysis_version": mda.__version__,
        "tpr": tpr_status,
        "fallback": {
            "topology_format": "GRO",
            "trajectory_format": "XTC",
            "n_atoms": atom_count,
            "n_residues": len(universe.residues),
            "n_frames": frame_count,
            "first_time_ps": times[0],
            "last_time_ps": times[-1],
            "first_dimensions_A_deg": first_dimensions,
            "last_dimensions_A_deg": last_dimensions,
            "finite_coordinates_all_frames": finite_coordinates,
            "finite_box_all_frames": finite_dimensions,
            "bond_count": bond_count,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tpr", required=True)
    parser.add_argument("--gro", required=True)
    parser.add_argument("--xtc", required=True)
    args = parser.parse_args()
    try:
        result = _probe(args)
    except Exception as exc:
        print(f"MDAnalysis probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
