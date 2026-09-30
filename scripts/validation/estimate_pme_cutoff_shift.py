#!/usr/bin/env python3
"""Estimate the GROMACS Verlet PME direct-potential cutoff-shift contribution."""

from __future__ import annotations

import argparse
import hashlib
import json
from math import erfc
from pathlib import Path
from typing import Any

import numpy as np
import parmed as pmd
from scipy.spatial import cKDTree

# GROMACS Coulomb constant converted to kcal mol^-1 Angstrom e^-2.
COULOMB_KCAL_ANGSTROM = 138.935456 * 10.0 / 4.184


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def estimate(
    amber_prmtop: Path,
    gromacs_topology: Path,
    gromacs_gro: Path,
    alpha_per_A: float,
    cutoff_A: float,
) -> dict[str, Any]:
    amber = pmd.load_file(str(amber_prmtop), xyz=str(gromacs_gro))
    gromacs = pmd.load_file(str(gromacs_topology), xyz=str(gromacs_gro))
    if len(amber.atoms) != len(gromacs.atoms):
        raise ValueError("Amber and GROMACS atom counts differ")
    if any(
        (a.residue.name, a.name) != (g.residue.name, g.name)
        for a, g in zip(amber.atoms, gromacs.atoms, strict=True)
    ):
        raise ValueError("Amber/GROMACS ordered residue/atom identities differ")

    box = np.asarray(gromacs.box, dtype=np.float64)
    if box.shape[0] < 6 or not np.allclose(box[3:6], 90.0, atol=1e-3):
        raise ValueError("this estimate currently supports orthorhombic boxes only")
    lengths = box[:3]
    coordinates = np.asarray([[atom.xx, atom.xy, atom.xz] for atom in gromacs.atoms])
    if np.any(coordinates < 0) or np.any(coordinates >= lengths):
        raise ValueError("GRO coordinates must be wrapped into the orthorhombic box")
    amber_charges = np.asarray([atom.charge for atom in amber.atoms], dtype=np.float64)
    gromacs_charges = np.asarray([atom.charge for atom in gromacs.atoms], dtype=np.float64)
    max_charge_difference = float(np.max(np.abs(amber_charges - gromacs_charges)))
    if max_charge_difference > 1e-6:
        raise ValueError(
            f"serialized Amber/GROMACS charges differ by {max_charge_difference:.8g} e"
        )

    candidates = cKDTree(coordinates, boxsize=lengths).query_pairs(cutoff_A, output_type="ndarray")
    if len(candidates):
        displacement = coordinates[candidates[:, 0]] - coordinates[candidates[:, 1]]
        displacement -= lengths * np.rint(displacement / lengths)
        within_cutoff = np.sum(displacement * displacement, axis=1) < cutoff_A**2
        candidates = candidates[within_cutoff]

    exclusions = {
        tuple(sorted((atom.idx, other)))
        for atom in gromacs.atoms
        for other in atom.nonbonded_exclusions()
        if atom.idx != other
    }
    adjusted_14 = {
        tuple(sorted((adjust.atom1.idx, adjust.atom2.idx))) for adjust in gromacs.adjusts
    }
    regular = np.asarray(
        [
            pair
            for pair in candidates
            if (int(pair[0]), int(pair[1])) not in exclusions
            and (int(pair[0]), int(pair[1])) not in adjusted_14
        ],
        dtype=np.int64,
    )
    if len(regular) == 0:
        raise ValueError("no regular nonbonded pairs remain inside the cutoff")
    pair_charge_product_sum = float(
        np.sum(gromacs_charges[regular[:, 0]] * gromacs_charges[regular[:, 1]])
    )
    shift_per_charge_product = COULOMB_KCAL_ANGSTROM * erfc(alpha_per_A * cutoff_A) / cutoff_A
    estimated_gromacs_minus_unshifted = -shift_per_charge_product * pair_charge_product_sum

    inputs = (amber_prmtop, gromacs_topology, gromacs_gro)
    return {
        "schema": "caddsuite.pme_cutoff_shift_estimate/1",
        "alpha_per_angstrom": alpha_per_A,
        "cutoff_angstrom": cutoff_A,
        "erfc_alpha_cutoff": erfc(alpha_per_A * cutoff_A),
        "coulomb_constant_kcal_mol_angstrom_per_e2": COULOMB_KCAL_ANGSTROM,
        "atom_count": len(amber.atoms),
        "box_angstrom": lengths.tolist(),
        "candidate_pairs_within_cutoff": len(candidates),
        "symmetric_exclusion_pair_count": len(exclusions),
        "adjusted_1_4_pair_count": len(adjusted_14),
        "regular_pairs_used": len(regular),
        "regular_pair_charge_product_sum_e2": pair_charge_product_sum,
        "shift_per_charge_product_kcal_mol": shift_per_charge_product,
        "estimated_gromacs_minus_unshifted_direct_energy_kcal_mol": (
            estimated_gromacs_minus_unshifted
        ),
        "max_serialized_charge_difference_e": max_charge_difference,
        "inputs": [{"path": str(path.resolve()), "sha256": sha256(path)} for path in inputs],
        "limitation": (
            "This estimates only the constant Verlet PME direct-potential shift over "
            "regular pairs inside the cutoff. It is not a total PME energy correction "
            "or an Amber/GROMACS equivalence test."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amber-prmtop", type=Path, required=True)
    parser.add_argument("--gromacs-topology", type=Path, required=True)
    parser.add_argument("--gromacs-gro", type=Path, required=True)
    parser.add_argument("--alpha-per-A", type=float, required=True)
    parser.add_argument("--cutoff-A", type=float, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.alpha_per_A <= 0 or args.cutoff_A <= 0:
        parser.error("--alpha-per-A and --cutoff-A must be positive")
    try:
        result = estimate(
            args.amber_prmtop,
            args.gromacs_topology,
            args.gromacs_gro,
            args.alpha_per_A,
            args.cutoff_A,
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
