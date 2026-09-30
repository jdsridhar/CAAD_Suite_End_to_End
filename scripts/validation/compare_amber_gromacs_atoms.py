#!/usr/bin/env python3
"""Compare ordered per-atom records in an Amber system and ParmEd GROMACS export."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import parmed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atom_identity(atom: Any) -> tuple[str, int, str, int]:
    return (
        str(atom.residue.name),
        int(atom.residue.number),
        str(atom.name),
        int(atom.atomic_number),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amber-prmtop", required=True, type=Path)
    parser.add_argument("--amber-coordinates", required=True, type=Path)
    parser.add_argument("--gromacs-topology", required=True, type=Path)
    parser.add_argument("--gromacs-coordinates", required=True, type=Path)
    args = parser.parse_args()

    amber = parmed.load_file(str(args.amber_prmtop), xyz=str(args.amber_coordinates))
    gromacs = parmed.load_file(str(args.gromacs_topology), xyz=str(args.gromacs_coordinates))
    if len(amber.atoms) != len(gromacs.atoms):
        raise SystemExit(
            f"atom-count mismatch: Amber={len(amber.atoms)}, GROMACS={len(gromacs.atoms)}"
        )

    identity_mismatches = []
    charge_differences: list[float] = []
    sigma_differences: list[float] = []
    epsilon_differences: list[float] = []
    coordinate_differences: list[float] = []
    for index in range(len(amber.atoms)):
        amber_atom = amber.atoms[index]
        gromacs_atom = gromacs.atoms[index]
        amber_identity = atom_identity(amber_atom)
        gromacs_identity = atom_identity(gromacs_atom)
        if amber_identity != gromacs_identity:
            identity_mismatches.append(
                {
                    "atom_index_zero_based": index,
                    "amber": amber_identity,
                    "gromacs": gromacs_identity,
                }
            )
        charge_differences.append(float(gromacs_atom.charge - amber_atom.charge))
        sigma_differences.append(float(gromacs_atom.sigma - amber_atom.sigma))
        epsilon_differences.append(float(gromacs_atom.epsilon - amber_atom.epsilon))
        coordinate_differences.append(
            math.sqrt(
                (float(gromacs_atom.xx - amber_atom.xx) ** 2)
                + (float(gromacs_atom.xy - amber_atom.xy) ** 2)
                + (float(gromacs_atom.xz - amber_atom.xz) ** 2)
            )
        )

    if identity_mismatches:
        raise SystemExit(
            json.dumps(
                {"identity_mismatches": identity_mismatches[:20], "count": len(identity_mismatches)}
            )
        )

    result = {
        "parmed_version": parmed.__version__,
        "atom_count": len(amber.atoms),
        "ordered_atom_identity_match": True,
        "charge": {
            "max_abs_delta_e": max(map(abs, charge_differences), default=0.0),
            "rms_delta_e": math.sqrt(
                sum(value * value for value in charge_differences) / max(len(charge_differences), 1)
            ),
            "net_delta_e": sum(charge_differences),
        },
        "per_atom_lj": {
            "sigma_max_abs_delta_angstrom": max(map(abs, sigma_differences), default=0.0),
            "epsilon_max_abs_delta_kcal_mol": max(map(abs, epsilon_differences), default=0.0),
        },
        "coordinates": {
            "max_atom_displacement_angstrom": max(coordinate_differences, default=0.0),
            "rms_atom_displacement_angstrom": math.sqrt(
                sum(value * value for value in coordinate_differences)
                / max(len(coordinate_differences), 1)
            ),
        },
        "input_sha256": {
            "amber_prmtop": sha256(args.amber_prmtop),
            "amber_coordinates": sha256(args.amber_coordinates),
            "gromacs_topology": sha256(args.gromacs_topology),
            "gromacs_coordinates": sha256(args.gromacs_coordinates),
        },
        "limitations": [
            "Does not compare pair-specific nonbonded parameters or exclusions.",
            "Does not establish PME energy equivalence, force equivalence, or MD stability.",
        ],
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
