"""Create charge-isolated Amber/GROMACS topology copies for PME diagnostics.

The input fixtures are read-only. The selected residue retains its charges;
all other charges are zeroed in derived Amber and GROMACS topology files.
Coordinates are taken from the supplied GRO file and written as an Amber
restart so both engines evaluate identical coordinates and box dimensions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import parmed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atom_identity(atom: parmed.Atom) -> tuple[str, str]:
    return atom.residue.name, atom.name


def prepare(source: Path, output: Path, residue_index: int) -> Path:
    source = source.resolve()
    output = output.resolve()
    inputs = {
        "amber_topology": source / "system.prmtop",
        "amber_coordinates": source / "system.inpcrd",
        "gromacs_topology": source / "topol.top",
        "gromacs_coordinates": source / "system.gro",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing source inputs: " + ", ".join(missing))
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("Source and output directories must not overlap")

    amber = parmed.load_file(str(inputs["amber_topology"]), str(inputs["amber_coordinates"]))
    gromacs = parmed.load_file(
        str(inputs["gromacs_topology"]), xyz=str(inputs["gromacs_coordinates"])
    )
    if len(amber.atoms) != len(gromacs.atoms):
        raise ValueError("Amber/GROMACS atom counts differ")
    amber_ids = [atom_identity(atom) for atom in amber.atoms]
    gromacs_ids = [atom_identity(atom) for atom in gromacs.atoms]
    if amber_ids != gromacs_ids:
        raise ValueError("Amber/GROMACS atom order or identity differs")
    if not 0 <= residue_index < len(gromacs.residues):
        raise ValueError(f"Residue index {residue_index} is out of range")

    charge_delta = max(
        abs(float(a.charge) - float(g.charge))
        for a, g in zip(amber.atoms, gromacs.atoms, strict=True)
    )
    if charge_delta > 1e-6:
        raise ValueError(f"Source per-atom charges differ by {charge_delta:g} e")

    selected = gromacs.residues[residue_index]
    selected_charge = float(sum(atom.charge for atom in selected.atoms))
    selected_charges_amber = [float(atom.charge) for atom in amber.residues[residue_index].atoms]
    selected_charges_gromacs = [float(atom.charge) for atom in selected.atoms]
    if abs(selected_charge) > 1e-5:
        raise ValueError(
            f"Selected residue net charge {selected_charge:.8g} e is not neutral; "
            "this diagnostic requires a neutral isolated charge group"
        )
    output.mkdir(parents=True, exist_ok=True)

    for structure in (amber, gromacs):
        for atom in structure.atoms:
            if atom.residue.idx != residue_index:
                atom.charge = 0.0

    amber_top = output / "isolated.prmtop"
    gromacs_top = output / "isolated.top"
    restart = output / "isolated.rst7"
    amber.save(str(amber_top), overwrite=True)
    gromacs.save(str(gromacs_top), format="gromacs", overwrite=True)

    xyz = np.asarray(gromacs.coordinates, dtype=np.float64)
    restart_data = parmed.amber.Rst7(
        natom=len(gromacs.atoms), title=f"Charge-isolated residue {residue_index}"
    )
    restart_data.coordinates = xyz.reshape(-1).tolist()
    restart_data.box = np.asarray(gromacs.box, dtype=np.float64).tolist()
    restart_data.write(str(restart))

    # Reload both topologies and verify atom order, charge isolation and the
    # preserved selected-residue charge before any engine is launched.
    amber_check = parmed.load_file(str(amber_top))
    gromacs_check = parmed.load_file(str(gromacs_top), xyz=str(inputs["gromacs_coordinates"]))
    if [atom_identity(atom) for atom in amber_check.atoms] != amber_ids:
        raise ValueError("Saved Amber topology changed atom identity/order")
    if [atom_identity(atom) for atom in gromacs_check.atoms] != gromacs_ids:
        raise ValueError("Saved GROMACS topology changed atom identity/order")
    for structure in (amber_check, gromacs_check):
        for atom in structure.atoms:
            if atom.residue.idx != residue_index and atom.charge != 0.0:
                raise ValueError("A non-selected atom retained nonzero charge")
    for checked, original in (
        (amber_check.residues[residue_index], selected_charges_amber),
        (gromacs_check.residues[residue_index], selected_charges_gromacs),
    ):
        if len(checked.atoms) != len(original) or any(
            abs(float(atom.charge) - charge) > 1e-6
            for atom, charge in zip(checked.atoms, original, strict=True)
        ):
            raise ValueError("Saved topology changed a selected-residue atom charge")

    manifest = {
        "selected_residue_index": residue_index,
        "selected_residue_name": selected.name,
        "selected_residue_atom_count": len(selected.atoms),
        "selected_residue_net_charge_e": selected_charge,
        "max_source_per_atom_charge_delta_e": charge_delta,
        "amber_charge_sum_after_isolation_e": float(sum(a.charge for a in amber_check.atoms)),
        "gromacs_charge_sum_after_isolation_e": float(sum(a.charge for a in gromacs_check.atoms)),
        "atom_count": len(amber_check.atoms),
        "source_sha256": {key: sha256(path) for key, path in inputs.items()},
        "derived_sha256": {path.name: sha256(path) for path in (amber_top, gromacs_top, restart)},
        "coordinate_source": "GROMACS GRO; restart uses identical coordinate values and box",
    }
    manifest_path = output / "preparation-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="Directory with paired source files"
    )
    parser.add_argument("--output", type=Path, required=True, help="New derived-output directory")
    parser.add_argument(
        "--residue-index", type=int, required=True, help="Zero-based neutral residue index"
    )
    args = parser.parse_args()
    manifest = prepare(args.source, args.output, args.residue_index)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
