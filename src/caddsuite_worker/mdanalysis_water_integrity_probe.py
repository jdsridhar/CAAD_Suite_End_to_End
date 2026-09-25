"""Measure explicit water-residue whole-molecule geometry in a staged GRO/XTC pair."""

from __future__ import annotations

import argparse
import json
import re
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any


def _input(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"input path is not a confined canonical relative path: {value!r}")
    path = root.joinpath(*relative.parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"input path escapes the private stage or is not a file: {value!r}")
    return path


def _probe(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9]{1,5}", args.water_resname):
        raise ValueError("water residue name must be one to five ASCII letters or digits")
    root = Path.cwd().resolve(strict=True)
    gro = _input(root, args.gro)
    xtc = _input(root, args.xtc)
    mda = import_module("MDAnalysis")
    np = import_module("numpy")
    universe = mda.Universe(str(gro), str(xtc))
    residues = [
        residue
        for residue in universe.residues
        if residue.resname == args.water_resname and len(residue.atoms) == 3
    ]
    if not residues:
        raise ValueError(f"no three-atom {args.water_resname} residues were found")
    indices = np.asarray([residue.atoms.indices for residue in residues], dtype=np.int64)
    frames: list[dict[str, float | int]] = []
    for timestep in universe.trajectory:
        xyz = universe.atoms.positions[indices]
        differences = xyz[:, :, None, :] - xyz[:, None, :, :]
        diameters = np.linalg.norm(differences, axis=-1).max(axis=(1, 2))
        frames.append(
            {
                "time_ps": float(timestep.time),
                "broken_residues": int((diameters > args.max_diameter_a).sum()),
                "maximum_diameter_A": float(diameters.max()),
            }
        )
    return {
        "protocol": "caddsuite.mdanalysis-water-integrity-probe/1",
        "mdanalysis_version": mda.__version__,
        "water_resname": args.water_resname,
        "water_residue_count": len(residues),
        "max_diameter_threshold_A": args.max_diameter_a,
        "n_frames": len(frames),
        "frames": frames,
        "maximum_broken_residues": max(int(frame["broken_residues"]) for frame in frames),
        "maximum_observed_diameter_A": max(float(frame["maximum_diameter_A"]) for frame in frames),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gro", required=True)
    parser.add_argument("--xtc", required=True)
    parser.add_argument("--water-resname", required=True)
    parser.add_argument("--max-diameter-a", type=float, default=2.5)
    args = parser.parse_args()
    if args.max_diameter_a <= 0:
        parser.error("--max-diameter-a must be positive")
    print(json.dumps(_probe(args), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
