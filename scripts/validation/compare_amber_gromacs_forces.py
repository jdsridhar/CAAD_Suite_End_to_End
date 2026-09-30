#!/usr/bin/env python3
"""Compare Amber Sander debug-force dump with GROMACS TRR forces."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import MDAnalysis as mda
import numpy as np

AMBER_KCAL_TO_BASE_KJ = 4.184


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_amber_debug_force_dump(path: Path) -> tuple[np.ndarray, np.ndarray]:
    lines = path.read_text(encoding="ascii").splitlines()
    try:
        atom_count = int(lines[0].strip())
    except (IndexError, ValueError) as exc:
        raise ValueError("Amber debug-force dump must start with its atom count") from exc
    if atom_count <= 0 or len(lines) < atom_count + 2:
        raise ValueError("Amber debug-force dump is truncated")

    def read_vectors(start: int, count: int, label: str) -> np.ndarray:
        rows: list[list[float]] = []
        for line_number, line in enumerate(lines[start : start + count], start=start + 1):
            fields = line.split()
            if len(fields) != 3:
                raise ValueError(f"Expected 3 {label} values at line {line_number}")
            try:
                rows.append([float(value) for value in fields])
            except ValueError as exc:
                raise ValueError(f"Invalid {label} value at line {line_number}") from exc
        values = np.asarray(rows, dtype=np.float64)
        if values.shape != (count, 3) or not np.isfinite(values).all():
            raise ValueError(f"Invalid {label} array")
        return values

    coordinates = read_vectors(1, atom_count, "coordinate")
    force_header = next((index for index, line in enumerate(lines) if "Total Force" in line), None)
    if force_header is None:
        raise ValueError("Amber debug-force dump has no Total Force block")
    forces = read_vectors(force_header + 1, atom_count, "force")
    return coordinates, forces


def statistics(reference: np.ndarray, observed: np.ndarray) -> dict[str, float]:
    difference = observed - reference
    denominator = float(np.sum(observed * observed))
    correlation = float(np.corrcoef(reference.ravel(), observed.ravel())[0, 1])
    return {
        "force_component_rmse_kj_mol_angstrom": float(np.sqrt(np.mean(difference**2))),
        "force_max_abs_component_error_kj_mol_angstrom": float(np.max(np.abs(difference))),
        "relative_vector_rmse_percent": (
            float(100.0 * np.sqrt(np.sum(difference * difference) / denominator))
            if denominator > 0
            else 0.0
        ),
        "component_pearson_correlation": correlation,
        "amber_force_rms_kj_mol_angstrom": float(np.sqrt(np.mean(reference**2))),
        "gromacs_force_rms_kj_mol_angstrom": float(np.sqrt(np.mean(observed**2))),
    }


def parse_group(value: str) -> tuple[str, str]:
    label, separator, selection = value.partition("=")
    if not separator or not label.strip() or not selection.strip():
        raise argparse.ArgumentTypeError("group must have LABEL=MDAnalysis selection syntax")
    return label.strip(), selection.strip()


def compare(
    amber_dump: Path,
    topology: Path,
    trajectory: Path,
    frame: int,
    groups: list[tuple[str, str]],
    coordinate_tolerance_A: float,
    background_trajectory: Path | None = None,
    amber_subtract_dump: Path | None = None,
    add_trajectory: Path | None = None,
) -> dict[str, Any]:
    amber_coordinates, amber_forces_kcal = read_amber_debug_force_dump(amber_dump)
    amber_subtract_max_coordinate_error_A = None
    if amber_subtract_dump is not None:
        subtract_coordinates, subtract_forces_kcal = read_amber_debug_force_dump(
            amber_subtract_dump
        )
        if subtract_coordinates.shape != amber_coordinates.shape:
            raise ValueError("subtracted Amber force dump atom count differs")
        amber_subtract_max_coordinate_error_A = float(
            np.max(np.abs(subtract_coordinates - amber_coordinates))
        )
        if amber_subtract_max_coordinate_error_A > coordinate_tolerance_A:
            raise ValueError(
                "subtracted Amber force dump coordinate mismatch exceeds tolerance: "
                f"{amber_subtract_max_coordinate_error_A:.8g} A > "
                f"{coordinate_tolerance_A:.8g} A"
            )
        amber_forces_kcal = amber_forces_kcal - subtract_forces_kcal
    universe = mda.Universe(str(topology), str(trajectory))
    if not 0 <= frame < len(universe.trajectory):
        raise ValueError(f"frame {frame} is outside the trajectory")
    timestep = universe.trajectory[frame]
    if len(universe.atoms) != len(amber_coordinates):
        raise ValueError(
            f"atom-count mismatch: Amber={len(amber_coordinates)}, GROMACS={len(universe.atoms)}"
        )

    # MDAnalysis converts TRR force records from native kJ/(mol*nm) to its
    # base force unit kJ/(mol*Angstrom) when convert_units=True (the default).
    gromacs_forces = np.asarray(timestep.forces, dtype=np.float64).copy()
    gromacs_coordinates_A = np.asarray(universe.atoms.positions, dtype=np.float64)
    background_max_coordinate_error_A = None
    added_max_coordinate_error_A = None
    if background_trajectory is not None:
        background = mda.Universe(str(topology), str(background_trajectory))
        if len(background.atoms) != len(universe.atoms):
            raise ValueError("background trajectory atom count differs from full-force trajectory")
        if not 0 <= frame < len(background.trajectory):
            raise ValueError(f"frame {frame} is outside the background trajectory")
        background_timestep = background.trajectory[frame]
        background_coordinates_A = np.asarray(background.atoms.positions, dtype=np.float64)
        background_max_coordinate_error_A = float(
            np.max(np.abs(background_coordinates_A - gromacs_coordinates_A))
        )
        if background_max_coordinate_error_A > coordinate_tolerance_A:
            raise ValueError(
                "background trajectory coordinate mismatch exceeds requested tolerance: "
                f"{background_max_coordinate_error_A:.8g} A > "
                f"{coordinate_tolerance_A:.8g} A"
            )
        if not np.isclose(background_timestep.time, timestep.time, atol=1e-6, rtol=0):
            raise ValueError("background and full-force trajectory frame times differ")
        gromacs_forces -= np.asarray(background_timestep.forces, dtype=np.float64)
    if add_trajectory is not None:
        added = mda.Universe(str(topology), str(add_trajectory))
        if len(added.atoms) != len(universe.atoms):
            raise ValueError("added trajectory atom count differs from full-force trajectory")
        if not 0 <= frame < len(added.trajectory):
            raise ValueError(f"frame {frame} is outside the added trajectory")
        added_timestep = added.trajectory[frame]
        added_coordinates_A = np.asarray(added.atoms.positions, dtype=np.float64)
        added_max_coordinate_error_A = float(
            np.max(np.abs(added_coordinates_A - gromacs_coordinates_A))
        )
        if added_max_coordinate_error_A > coordinate_tolerance_A:
            raise ValueError(
                "added trajectory coordinate mismatch exceeds requested tolerance: "
                f"{added_max_coordinate_error_A:.8g} A > "
                f"{coordinate_tolerance_A:.8g} A"
            )
        if not np.isclose(added_timestep.time, timestep.time, atol=1e-6, rtol=0):
            raise ValueError("added and full-force trajectory frame times differ")
        gromacs_forces += np.asarray(added_timestep.forces, dtype=np.float64)
    amber_forces = amber_forces_kcal * AMBER_KCAL_TO_BASE_KJ
    coordinate_error_A = np.abs(gromacs_coordinates_A - amber_coordinates)
    max_coordinate_error_A = float(np.max(coordinate_error_A))
    if max_coordinate_error_A > coordinate_tolerance_A:
        raise ValueError(
            "coordinate mismatch exceeds requested tolerance: "
            f"{max_coordinate_error_A:.8g} A > {coordinate_tolerance_A:.8g} A"
        )

    all_groups = [("all", np.arange(len(universe.atoms), dtype=np.int64))]
    seen_labels = {"all"}
    for label, selection in groups:
        if label in seen_labels:
            raise ValueError(f"duplicate or reserved group label: {label}")
        seen_labels.add(label)
        indices = universe.select_atoms(selection).indices
        if len(indices) == 0:
            raise ValueError(f"selection for group {label!r} matched no atoms")
        all_groups.append((label, indices))

    group_results = {
        label: {
            "atom_count": len(indices),
            **statistics(amber_forces[indices], gromacs_forces[indices]),
        }
        for label, indices in all_groups
    }
    files = (amber_dump, topology, trajectory)
    files += (background_trajectory,) if background_trajectory is not None else ()
    files += (amber_subtract_dump,) if amber_subtract_dump is not None else ()
    files += (add_trajectory,) if add_trajectory is not None else ()
    return {
        "schema": "caddsuite.amber_gromacs_force_comparison/1",
        "frame_index": frame,
        "frame_time_ps": float(timestep.time),
        "atom_count": len(universe.atoms),
        "coordinate_max_abs_difference_A": max_coordinate_error_A,
        "coordinate_tolerance_A": coordinate_tolerance_A,
        "background_coordinate_max_abs_difference_A": background_max_coordinate_error_A,
        "amber_subtract_coordinate_max_abs_difference_A": (amber_subtract_max_coordinate_error_A),
        "added_coordinate_max_abs_difference_A": added_max_coordinate_error_A,
        "force_isolation": {
            "amber": (
                "primary Amber force minus secondary Amber force dump"
                if amber_subtract_dump is not None
                else "primary Amber force dump"
            ),
            "gromacs": {
                "primary": "primary GROMACS force TRR",
                "subtract": (
                    "matched background force TRR" if background_trajectory is not None else None
                ),
                "add": ("matched additional force TRR" if add_trajectory is not None else None),
            },
        },
        "force_unit": "kJ/(mol*Angstrom)",
        "amber_force_conversion": "kcal/(mol*Angstrom) x 4.184",
        "gromacs_native_force_unit": universe.trajectory.units.get("force"),
        "groups": group_results,
        "inputs": [{"path": str(path.resolve()), "sha256": sha256(path)} for path in files],
        "software": {
            "MDAnalysis": mda.__version__,
            "numpy": np.__version__,
        },
        "interpretation": (
            "Single-frame implementation comparison only; no universal tolerance "
            "or engine-compatibility qualification is implied."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amber-forcedump", type=Path, required=True)
    parser.add_argument(
        "--gromacs-topology",
        type=Path,
        required=True,
        help="GRO or other MDAnalysis topology",
    )
    parser.add_argument("--gromacs-force-trr", type=Path, required=True)
    parser.add_argument(
        "--gromacs-background-force-trr",
        type=Path,
        help="optional matched-coordinate background TRR to subtract from GROMACS forces",
    )
    parser.add_argument(
        "--amber-subtract-forcedump",
        type=Path,
        help="optional matched-coordinate Amber force dump to subtract from the primary dump",
    )
    parser.add_argument(
        "--gromacs-add-force-trr",
        type=Path,
        help="optional matched-coordinate force TRR to add to the primary GROMACS force",
    )
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument(
        "--group",
        type=parse_group,
        action="append",
        default=[],
        metavar="LABEL=SELECTION",
        help="optional MDAnalysis atom group; can be repeated",
    )
    parser.add_argument("--coordinate-tolerance-A", type=float, default=1e-4)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.coordinate_tolerance_A <= 0:
        parser.error("--coordinate-tolerance-A must be positive")
    try:
        result = compare(
            args.amber_forcedump,
            args.gromacs_topology,
            args.gromacs_force_trr,
            args.frame,
            args.group,
            args.coordinate_tolerance_A,
            args.gromacs_background_force_trr,
            args.amber_subtract_forcedump,
            args.gromacs_add_force_trr,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
