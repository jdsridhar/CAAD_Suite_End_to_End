"""Identity-gated docked-pose loading and symmetry-aware RMSD helpers."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem import rdMolAlign


def load_docked_pose(
    path: str, expected_smiles: str, charge: int, multiplicity: int
) -> dict[str, Any]:
    """Load one normalized SDF pose and verify its graph against the selected form.

    The identity gate runs before any docked-geometry energy is evaluated. Platform
    inputs use normalized SDF with explicit hydrogens and registered bond orders.
    """
    source = Path(path)
    if source.suffix.casefold() != ".sdf":
        raise ValueError("platform pose analysis accepts only normalized SDF artifacts")
    molecules = list(Chem.SDMolSupplier(str(source), removeHs=False, sanitize=True))
    if len(molecules) != 1 or molecules[0] is None:
        raise ValueError("normalized pose SDF must contain exactly one valid molecule")
    molecule = molecules[0]
    if molecule.GetNumConformers() != 1 or not molecule.GetConformer().Is3D():
        raise ValueError("normalized pose must contain exactly one 3D conformer")

    form = Chem.MolFromSmiles(expected_smiles)
    if form is None:
        raise ValueError("selected CompoundForm SMILES is invalid")
    pose_charge = int(Chem.GetFormalCharge(molecule))
    if pose_charge != charge:
        raise ValueError("pose formal charge differs from the selected CompoundForm")
    form_smiles = Chem.MolToSmiles(form, canonical=True, isomericSmiles=True)
    pose_smiles = Chem.MolToSmiles(Chem.RemoveHs(molecule), canonical=True, isomericSmiles=True)
    if pose_smiles != form_smiles:
        raise ValueError("pose connectivity or stereochemistry differs from the selected form")

    # Canonical identity is the first gate; an explicit graph match establishes
    # the atom correspondence needed for later coordinates and provenance.
    pose_heavy = Chem.RemoveHs(molecule)
    matches = pose_heavy.GetSubstructMatches(form, uniquify=False, maxMatches=10000)
    if not matches or any(len(match) != form.GetNumAtoms() for match in matches):
        raise ValueError("pose has no complete substructure atom mapping to the selected form")
    atom_map = min(matches)

    conf = molecule.GetConformer()
    for atom_index in range(molecule.GetNumAtoms()):
        position = conf.GetAtomPosition(atom_index)
        if not all(math.isfinite(value) for value in (position.x, position.y, position.z)):
            raise ValueError("pose contains a non-finite coordinate")
    expected_atoms = Chem.AddHs(Chem.RemoveHs(molecule)).GetNumAtoms()
    if molecule.GetNumAtoms() != expected_atoms:
        raise ValueError("normalized pose SDF must contain all explicit hydrogen coordinates")

    electrons = sum(atom.GetAtomicNum() for atom in molecule.GetAtoms()) - charge  # type: ignore[no-untyped-call]
    if electrons < multiplicity - 1 or (electrons - multiplicity + 1) % 2:
        raise ValueError("pose electron count is inconsistent with the requested multiplicity")

    rows = [f"{charge} {multiplicity}"]
    for atom in molecule.GetAtoms():  # type: ignore[no-untyped-call]
        position = conf.GetAtomPosition(atom.GetIdx())
        rows.append(f"{atom.GetSymbol()} {position.x:.12f} {position.y:.12f} {position.z:.12f}")
    rows.append("units angstrom")
    return {
        "mol": molecule,
        "geometry_block": "\n".join(rows),
        "smiles": pose_smiles,
        "atom_map_form_to_pose": tuple((index, target) for index, target in enumerate(atom_map)),
    }


def compute_strain_and_rmsd(
    optimized_geometry_block: str, docked_smiles: str, docked_mol: Any
) -> dict[str, Any]:
    """Map optimized coordinates onto the docked graph, then compute best-fit RMSD.

    Psi4 preserves the input atom order during optimization. We verify the full
    element sequence before assigning optimized coordinates to the original
    molecular graph; RDKit then enumerates symmetry-equivalent heavy-atom matches.
    """
    del docked_smiles  # identity was checked against the registered form on load
    rows: list[tuple[str, float, float, float]] = []
    for line in optimized_geometry_block.strip().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        try:
            xyz = (float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            continue
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError("optimized geometry contains a non-finite coordinate")
        rows.append((parts[0], *xyz))

    if len(rows) != docked_mol.GetNumAtoms():
        raise ValueError(
            f"optimized geometry has {len(rows)} atoms; docked pose has {docked_mol.GetNumAtoms()}"
        )
    symbols = [atom.GetSymbol() for atom in docked_mol.GetAtoms()]
    if [row[0] for row in rows] != symbols:
        raise ValueError("optimized geometry element order differs from the pose input order")

    probe = Chem.Mol(docked_mol)
    probe_conf = probe.GetConformer()
    for atom_index, row in enumerate(rows):
        probe_conf.SetAtomPosition(atom_index, row[1:])
    probe_heavy = Chem.RemoveHs(probe)
    reference_heavy = Chem.RemoveHs(Chem.Mol(docked_mol))
    mappings = reference_heavy.GetSubstructMatches(probe_heavy, uniquify=False, maxMatches=10000)
    if not mappings:
        raise ValueError("optimized geometry has no graph-preserving atom mapping to the pose")

    best_rmsd: float | None = None
    best_probe = None
    best_mapping: tuple[int, ...] | None = None
    for mapping in mappings:
        aligned = Chem.Mol(probe_heavy)
        pairs = [(probe_index, pose_index) for probe_index, pose_index in enumerate(mapping)]
        rmsd = float(rdMolAlign.AlignMol(aligned, reference_heavy, atomMap=pairs))
        if best_rmsd is None or rmsd < best_rmsd:
            best_rmsd = rmsd
            best_probe = aligned
            best_mapping = mapping

    if best_probe is None or best_mapping is None or best_rmsd is None:
        raise ValueError("no valid symmetry-equivalent heavy-atom mapping was found")
    optimized_coords = [
        tuple(best_probe.GetConformer().GetAtomPosition(i)) for i in range(best_probe.GetNumAtoms())
    ]
    docked_coords = [
        tuple(reference_heavy.GetConformer().GetAtomPosition(i))
        for i in range(reference_heavy.GetNumAtoms())
    ]
    return {
        "rmsd_ang": best_rmsd,
        "optimized_coords": optimized_coords,
        "docked_coords": docked_coords,
        "symbols": [atom.GetSymbol() for atom in best_probe.GetAtoms()],  # type: ignore[no-untyped-call]
        "heavy_atom_map": tuple((index, target) for index, target in enumerate(best_mapping)),
    }
