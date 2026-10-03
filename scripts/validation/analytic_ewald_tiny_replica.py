"""Compare G-MD-57 ethanol–water replica pairs with analytic Ewald sums.

Requires MDAnalysis, NumPy and SciPy. This is a diagnostic, not a compatibility
qualification or energy acceptance test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import MDAnalysis as mda
import numpy as np
from scipy.special import erfc

AMBER_COULOMB_KCAL_ANGSTROM = 332.0522173
GMX_COULOMB_KCAL_ANGSTROM = 138.935456 * 10.0 / 4.184
KCAL_PER_KJ = 1.0 / 4.184
ALPHA_PER_ANGSTROM = 0.27511
REAL_CUTOFF_ANGSTROM = 10.0
LIGAND_RESIDUE_INDEX = 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_xvg_at_time(path: Path, time_ps: float) -> np.ndarray:
    records = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("@", "#")):
            continue
        records.append([float(value) for value in stripped.split()])
    matches = [row for row in records if math.isclose(row[0], time_ps, abs_tol=1e-5)]
    if len(matches) != 1 or len(matches[0]) != 4:
        raise ValueError(f"Expected one 4-column XVG row at {time_ps} ps in {path}")
    return np.asarray(matches[0][1:], dtype=float) * KCAL_PER_KJ


def ewald_pair(
    positions: np.ndarray,
    box: np.ndarray,
    ligand_indices: np.ndarray,
    water_indices: np.ndarray,
    charges: np.ndarray,
    kmax: float,
) -> tuple[float, float, int]:
    ligand_xyz, water_xyz = positions[ligand_indices], positions[water_indices]
    ligand_q, water_q = charges[ligand_indices], charges[water_indices]
    displacement = ligand_xyz[:, None, :] - water_xyz[None, :, :]
    displacement -= box * np.round(displacement / box)
    distance = np.linalg.norm(displacement, axis=-1)
    charge_product = ligand_q[:, None] * water_q[None, :]
    mask = (distance > 0) & (distance < REAL_CUTOFF_ANGSTROM)
    real_base = float(
        np.sum(charge_product[mask] * erfc(ALPHA_PER_ANGSTROM * distance[mask]) / distance[mask])
    )

    nmax = np.floor(kmax * box / (2 * math.pi)).astype(int)
    indices = np.stack(
        np.meshgrid(*(np.arange(-n, n + 1) for n in nmax), indexing="ij"), axis=-1
    ).reshape(-1, 3)
    indices = indices[np.any(indices != 0, axis=1)]
    vectors = 2 * math.pi * indices / box
    squared = np.einsum("ij,ij->i", vectors, vectors)
    reciprocal_sum = 0.0
    for start in range(0, len(vectors), 8192):
        part, k2 = vectors[start : start + 8192], squared[start : start + 8192]
        rho_l = np.exp(1j * (part @ ligand_xyz.T)) @ ligand_q
        rho_w = np.exp(1j * (part @ water_xyz.T)) @ water_q
        reciprocal_sum += float(
            np.sum(np.exp(-k2 / (4 * ALPHA_PER_ANGSTROM**2)) / k2 * np.real(rho_l * np.conj(rho_w)))
        )
    reciprocal_base = 4 * math.pi / float(np.prod(box)) * reciprocal_sum
    total_base = real_base + reciprocal_base
    return (
        GMX_COULOMB_KCAL_ANGSTROM * total_base,
        AMBER_COULOMB_KCAL_ANGSTROM * total_base,
        len(vectors),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--amber-topology", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kmax", type=float, default=2.5)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    table = args.capture / "pair-energies-flexible-consistent.csv"
    input_rows = list(csv.DictReader(table.open(newline="")))
    if len(input_rows) != 15:
        raise ValueError(f"Expected the 15 G-MD-57 pairs, found {len(input_rows)}")
    charges = None
    atom_names = None
    residue_ids = None
    results = []
    selection_manifest = args.capture / "selected-water-manifest.json"
    source_files = {
        "pair_table": table,
        "selected_water_manifest": selection_manifest,
        "amber_topology": args.amber_topology,
    }

    for row in input_rows:
        replica, time_ps = int(row["replica"]), float(row["time_ps"])
        water_index = int(row["water_residue_index"])
        frame = args.capture / f"replica-{replica}" / f"{int(time_ps):04d}ps"
        trajectory = frame / "LW" / "rerun-flexible-2.trr"
        universe = mda.Universe(str(args.amber_topology), str(trajectory))
        times = np.asarray([ts.time for ts in universe.trajectory])
        matches = np.flatnonzero(np.isclose(times, time_ps, atol=1e-5))
        if len(matches) != 1:
            raise ValueError(f"Expected one TRR frame at {time_ps} ps in {trajectory}")
        ts = universe.trajectory[int(matches[0])]
        if charges is None:
            charges = universe.atoms.charges.astype(float)
            atom_names = np.asarray(universe.atoms.names)
            residue_ids = np.asarray(universe.atoms.resindices)
        elif (
            len(universe.atoms) != len(charges)
            or not np.array_equal(np.asarray(universe.atoms.names), atom_names)
            or not np.array_equal(np.asarray(universe.atoms.resindices), residue_ids)
        ):
            raise ValueError("Atom count, order, or residue mapping changed across replicas")
        ligand_indices = np.flatnonzero(residue_ids == LIGAND_RESIDUE_INDEX)
        water_atoms = np.flatnonzero(residue_ids == water_index)
        if len(ligand_indices) != 9 or len(water_atoms) != 3:
            raise ValueError("Unexpected ethanol or water atom count")
        if not np.isclose(charges[ligand_indices].sum(), 0.0, atol=1e-6):
            raise ValueError("Selected ligand is not neutral within charge precision")
        if not np.isclose(charges[water_atoms].sum(), 0.0, atol=1e-6):
            raise ValueError("Selected water is not neutral within charge precision")
        positions = ts.positions.astype(float)
        box = ts.dimensions[:3].astype(float)
        masses = universe.atoms.masses.astype(float)
        ligand_heavy = ligand_indices[masses[ligand_indices] > 2.0]
        oxygen = water_atoms[atom_names[water_atoms] == "O"]
        if len(oxygen) != 1:
            raise ValueError("Selected water does not have exactly one named oxygen")
        delta = positions[ligand_heavy] - positions[oxygen[0]]
        delta -= box * np.round(delta / box)
        nearest_distance = float(np.min(np.linalg.norm(delta, axis=1)))
        if abs(nearest_distance - float(row["distance_A"])) > 0.0051:
            raise ValueError(
                f"Selected-water distance mismatch: {nearest_distance} A vs "
                f"recorded {row['distance_A']} A"
            )
        if np.any(box <= 2 * REAL_CUTOFF_ANGSTROM):
            raise ValueError("Cell dimensions must exceed twice the real-space cutoff")
        analytic_gmx, analytic_amber, n_vectors = ewald_pair(
            positions, box, ligand_indices, water_atoms, charges, args.kmax
        )

        component_paths = {
            "L": args.capture / "L" / f"replica-{replica}" / "coulomb-flexible.xvg",
            "W": frame / "W" / "coulomb-flexible-2.xvg",
            "LW": frame / "LW" / "coulomb-flexible-2.xvg",
        }
        comps = {key: read_xvg_at_time(path, time_ps) for key, path in component_paths.items()}
        real_gmx = float(comps["LW"][1] - comps["L"][1] - comps["W"][1])
        reciprocal_gmx = float(comps["LW"][2] - comps["L"][2] - comps["W"][2])
        result = {
            "replica": replica,
            "time_ps": int(time_ps),
            "water_residue_index": water_index,
            "snapshot_sha256": row.get("snapshot_sha256", ""),
            "box_x_A": float(box[0]),
            "box_y_A": float(box[1]),
            "box_z_A": float(box[2]),
            "nearest_ligand_heavy_water_oxygen_A": nearest_distance,
            "ligand_net_charge_e": float(charges[ligand_indices].sum()),
            "water_net_charge_e": float(charges[water_atoms].sum()),
            "reciprocal_vectors": n_vectors,
            "analytic_gromacs_kcal_mol": analytic_gmx,
            "analytic_amber_kcal_mol": analytic_amber,
            "gromacs_measured_kcal_mol": float(row["gromacs_pair_kcal_mol"]),
            "amber_measured_kcal_mol": float(row["amber_pair_kcal_mol"]),
            "gromacs_minus_amber_measured_kcal_mol": float(row["residual_kcal_mol"]),
            "gromacs_real_component_kcal_mol": real_gmx,
            "gromacs_reciprocal_component_kcal_mol": reciprocal_gmx,
            "analytic_gromacs_minus_measured_kcal_mol": (
                analytic_gmx - float(row["gromacs_pair_kcal_mol"])
            ),
            "analytic_amber_minus_measured_kcal_mol": (
                analytic_amber - float(row["amber_pair_kcal_mol"])
            ),
            "analytic_gromacs_minus_analytic_amber_kcal_mol": (analytic_gmx - analytic_amber),
        }
        results.append(result)
        source_files[f"replica-{replica}-{int(time_ps)}ps-trr"] = trajectory
        for key, path in component_paths.items():
            source_files[f"replica-{replica}-{int(time_ps)}ps-{key}-xvg"] = path
        print(f"completed replica {replica} at {time_ps:g} ps", flush=True)

    result_csv = args.output / "frame-results.csv"
    with result_csv.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    summary = {"n_frames": len(results), "kmax_inverse_angstrom": args.kmax}
    for key in (
        "gromacs_minus_amber_measured_kcal_mol",
        "analytic_gromacs_minus_analytic_amber_kcal_mol",
        "analytic_gromacs_minus_measured_kcal_mol",
        "analytic_amber_minus_measured_kcal_mol",
    ):
        values = np.asarray([row[key] for row in results])
        summary[key] = {
            "mean": float(values.mean()),
            "min": float(values.min()),
            "max": float(values.max()),
            "rmse": float(np.sqrt(np.mean(values**2))),
        }
    summary_json = args.output / "summary.json"
    summary_json.write_text(json.dumps(summary, indent=2) + "\n")
    manifest = {
        key: {"path": str(path), "sha256": sha256(path)} for key, path in source_files.items()
    }
    for path in (Path(__file__), result_csv, summary_json):
        manifest[path.name] = {"path": str(path), "sha256": sha256(path)}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
