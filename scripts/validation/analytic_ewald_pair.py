"""Compare isolated neutral-group PME energies with a direct Ewald lattice sum.

This diagnostic requires ParmEd, NumPy and SciPy in the validation environment.
It does not qualify cross-engine compatibility or define an acceptance tolerance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import parmed as p
from scipy.special import erfc

AMBER_COULOMB_KCAL_ANGSTROM = 332.0522173
GMX_COULOMB_KCAL_ANGSTROM = 138.935456 * 10.0 / 4.184
KCAL_PER_KJ = 1.0 / 4.184
ALPHA_PER_ANGSTROM = 0.27511
REAL_CUTOFF_ANGSTROM = 10.0
LIGAND_RESIDUE_INDEX = 126


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def xvg_coulomb_components(path: Path) -> np.ndarray:
    numeric = [
        line
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith(("@", "#"))
    ]
    values = np.atleast_2d(np.loadtxt(numeric, dtype=float))
    if values.shape[1] != 4:
        raise ValueError(f"Expected time + 3 Coulomb columns in {path}")
    return values[-1, 1:4] * KCAL_PER_KJ


def analytic_pair(
    frame: Path, water_residue_index: int, reciprocal_kmax: float
) -> dict[str, float | int]:
    source = frame / "source"
    system = p.load_file(str(source / "topol.top"), xyz=str(source / "system.gro"))
    if system.box is None or len(system.box) < 3:
        raise ValueError(f"Missing periodic box in {source / 'system.gro'}")
    box = np.asarray(system.box[:3], dtype=float)
    if len(system.box) >= 6 and not np.allclose(system.box[3:], 90.0, atol=1e-5):
        raise ValueError("This diagnostic currently supports orthorhombic cells only")
    if np.any(box <= 2 * REAL_CUTOFF_ANGSTROM):
        raise ValueError("Cell dimensions must exceed twice the real-space cutoff")

    ligand, water = system.residues[LIGAND_RESIDUE_INDEX], system.residues[water_residue_index]
    coordinates = np.asarray(system.coordinates, dtype=float).reshape(-1, 3)
    ligand_xyz = coordinates[[atom.idx for atom in ligand.atoms]]
    water_xyz = coordinates[[atom.idx for atom in water.atoms]]
    ligand_q = np.asarray([atom.charge for atom in ligand.atoms], dtype=float)
    water_q = np.asarray([atom.charge for atom in water.atoms], dtype=float)

    displacement = ligand_xyz[:, None, :] - water_xyz[None, :, :]
    displacement -= box * np.round(displacement / box)
    distance = np.linalg.norm(displacement, axis=-1)
    charge_product = ligand_q[:, None] * water_q[None, :]
    within_cutoff = (distance > 0) & (distance < REAL_CUTOFF_ANGSTROM)
    real_base = float(
        np.sum(
            charge_product[within_cutoff]
            * erfc(ALPHA_PER_ANGSTROM * distance[within_cutoff])
            / distance[within_cutoff]
        )
    )

    nmax = np.floor(reciprocal_kmax * box / (2 * math.pi)).astype(int)
    indices = np.stack(
        np.meshgrid(*(np.arange(-n, n + 1) for n in nmax), indexing="ij"), axis=-1
    ).reshape(-1, 3)
    indices = indices[np.any(indices != 0, axis=1)]
    reciprocal_vectors = 2 * math.pi * indices / box
    k_squared = np.einsum("ij,ij->i", reciprocal_vectors, reciprocal_vectors)
    reciprocal_sum = 0.0
    for start in range(0, len(reciprocal_vectors), 8192):
        vectors = reciprocal_vectors[start : start + 8192]
        squared = k_squared[start : start + 8192]
        rho_ligand = np.exp(1j * (vectors @ ligand_xyz.T)) @ ligand_q
        rho_water = np.exp(1j * (vectors @ water_xyz.T)) @ water_q
        reciprocal_sum += float(
            np.sum(
                np.exp(-squared / (4 * ALPHA_PER_ANGSTROM**2))
                / squared
                * np.real(rho_ligand * np.conj(rho_water))
            )
        )
    reciprocal_base = 4 * math.pi / float(np.prod(box)) * reciprocal_sum

    components = {
        group: xvg_coulomb_components(frame / group / "coulomb.xvg") for group in ("L", "W", "LW")
    }
    gmx_real = float(components["LW"][1] - components["L"][1] - components["W"][1])
    gmx_reciprocal = float(components["LW"][2] - components["L"][2] - components["W"][2])
    return {
        "reciprocal_vectors": len(reciprocal_vectors),
        "ligand_net_charge_e": float(ligand_q.sum()),
        "water_net_charge_e": float(water_q.sum()),
        "real_space_base": real_base,
        "reciprocal_space_base": reciprocal_base,
        "analytic_amber_kcal_mol": AMBER_COULOMB_KCAL_ANGSTROM * (real_base + reciprocal_base),
        "analytic_gromacs_kcal_mol": GMX_COULOMB_KCAL_ANGSTROM * (real_base + reciprocal_base),
        "gromacs_real_component_kcal_mol": gmx_real,
        "gromacs_reciprocal_component_kcal_mol": gmx_reciprocal,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True, help="G-MD-58 capture directory")
    parser.add_argument(
        "--output", type=Path, required=True, help="Directory for results and hashes"
    )
    parser.add_argument(
        "--kmax", type=float, default=2.5, help="Reciprocal-vector component cutoff, A^-1"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    source_csv = args.capture / "pair-energies.csv"
    with source_csv.open(newline="") as stream:
        input_rows = list(csv.DictReader(stream))
    if not input_rows:
        raise SystemExit("No pair rows found")

    results = []
    input_files = {"pair_energies_csv": source_csv}
    for row in input_rows:
        frame = args.capture / f"replica-{row['replica']}" / f"{int(row['time_ps']):04d}ps"
        calculated = analytic_pair(frame, int(row["water_residue_index"]), args.kmax)
        result = {
            "replica": row["replica"],
            "time_ps": row["time_ps"],
            "water_residue_index": row["water_residue_index"],
            "snapshot_sha256": row["snapshot_sha256"],
            "amber_pair_measured_kcal_mol": float(row["amber_pair"]),
            "gromacs_pair_measured_kcal_mol": float(row["gromacs_pair"]),
            "amber_minus_gromacs_measured_kcal_mol": float(row["residual"]),
            **calculated,
        }
        result["gromacs_real_delta_kcal_mol"] = (
            result["gromacs_real_component_kcal_mol"]
            - GMX_COULOMB_KCAL_ANGSTROM * result["real_space_base"]
        )
        result["gromacs_reciprocal_delta_kcal_mol"] = (
            result["gromacs_reciprocal_component_kcal_mol"]
            - GMX_COULOMB_KCAL_ANGSTROM * result["reciprocal_space_base"]
        )
        result["analytic_gromacs_minus_measured_kcal_mol"] = (
            result["analytic_gromacs_kcal_mol"] - result["gromacs_pair_measured_kcal_mol"]
        )
        result["analytic_amber_minus_measured_kcal_mol"] = (
            result["analytic_amber_kcal_mol"] - result["amber_pair_measured_kcal_mol"]
        )
        results.append(result)
        source = frame / "source"
        input_files[f"replica-{row['replica']}-{row['time_ps']}ps-gro"] = source / "system.gro"
        input_files[f"replica-{row['replica']}-{row['time_ps']}ps-topology"] = source / "topol.top"
        for group in ("L", "W", "LW"):
            input_files[f"replica-{row['replica']}-{row['time_ps']}ps-{group}-coulomb-xvg"] = (
                frame / group / "coulomb.xvg"
            )

    result_csv = args.output / "frame-results.csv"
    with result_csv.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    summary = {
        "n_frames": len(results),
        "kmax_inverse_angstrom": args.kmax,
        "ewald_alpha_inverse_angstrom": ALPHA_PER_ANGSTROM,
        "real_cutoff_angstrom": REAL_CUTOFF_ANGSTROM,
        "interpretation": (
            "Diagnostic comparison only; it does not qualify engine compatibility or set tolerance."
        ),
    }
    for field in (
        "amber_minus_gromacs_measured_kcal_mol",
        "gromacs_real_delta_kcal_mol",
        "gromacs_reciprocal_delta_kcal_mol",
        "analytic_gromacs_minus_measured_kcal_mol",
        "analytic_amber_minus_measured_kcal_mol",
    ):
        values = np.asarray([row[field] for row in results])
        summary[field] = {
            "mean": float(values.mean()),
            "min": float(values.min()),
            "max": float(values.max()),
            "rmse": float(np.sqrt(np.mean(values**2))),
        }
    summary_json = args.output / "summary.json"
    summary_json.write_text(json.dumps(summary, indent=2) + "\n")

    manifest = {
        name: {"path": str(path), "sha256": sha256(path)} for name, path in input_files.items()
    }
    for path in (Path(__file__), result_csv, summary_json):
        manifest[path.name] = {"path": str(path), "sha256": sha256(path)}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
