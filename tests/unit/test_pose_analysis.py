from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from caddsuite_worker.pose_analysis import compute_strain_and_rmsd, load_docked_pose


def _pose_sdf(path: Path, smiles: str = "CCO") -> tuple[str, Chem.Mol]:
    molecule = Chem.AddHs(Chem.MolFromSmiles(smiles))
    assert AllChem.EmbedMolecule(molecule, randomSeed=71) == 0
    permutation = list(reversed(range(molecule.GetNumAtoms())))
    reordered = Chem.RenumberAtoms(molecule, permutation)
    writer = Chem.SDWriter(str(path))
    writer.write(reordered)
    writer.close()
    canonical = Chem.MolToSmiles(Chem.RemoveHs(molecule), canonical=True, isomericSmiles=True)
    return canonical, reordered


def test_pose_identity_is_checked_against_registered_form_before_use(tmp_path):
    sdf = tmp_path / "ethanol.sdf"
    form_smiles, _ = _pose_sdf(sdf)
    pose = load_docked_pose(str(sdf), form_smiles, charge=0, multiplicity=1)
    assert pose["smiles"] == form_smiles
    assert len(pose["atom_map_form_to_pose"]) == 3
    assert len(pose["mol"].GetAtoms()) == 9

    with pytest.raises(ValueError, match="connectivity or stereochemistry"):
        load_docked_pose(str(sdf), "CCN", charge=0, multiplicity=1)


def test_pose_loader_rejects_charge_or_spin_mismatch(tmp_path):
    sdf = tmp_path / "ethanol.sdf"
    smiles, _ = _pose_sdf(sdf)
    with pytest.raises(ValueError, match="formal charge"):
        load_docked_pose(str(sdf), smiles, charge=1, multiplicity=2)
    with pytest.raises(ValueError, match="electron count"):
        load_docked_pose(str(sdf), smiles, charge=0, multiplicity=2)


def test_rmsd_maps_reordered_pose_atoms_and_symmetry_before_alignment(tmp_path):
    sdf = tmp_path / "ethanol.sdf"
    smiles, molecule = _pose_sdf(sdf)
    pose = load_docked_pose(str(sdf), smiles, charge=0, multiplicity=1)
    molecule = pose["mol"]
    molecule = pose["mol"]
    conf = molecule.GetConformer()
    rows = ["0 1"]
    for atom in molecule.GetAtoms():
        point = conf.GetAtomPosition(atom.GetIdx())
        # A proper rigid rotation and translation must leave fitted RMSD at zero.
        rows.append(
            f"{atom.GetSymbol()} {-point.y + 4.0:.12f} {point.x - 3.0:.12f} {point.z + 2.0:.12f}"
        )
    rows.append("units angstrom")

    result = compute_strain_and_rmsd("\n".join(rows), smiles, pose["mol"])
    assert result["rmsd_ang"] == pytest.approx(0.0, abs=3e-6)
    assert len(result["heavy_atom_map"]) == 3
    assert len({left for left, _ in result["heavy_atom_map"]}) == 3
    assert len({right for _, right in result["heavy_atom_map"]}) == 3


def test_rmsd_rejects_atom_order_that_cannot_be_recovered_from_xyz(tmp_path):
    sdf = tmp_path / "ethanol.sdf"
    smiles, molecule = _pose_sdf(sdf)
    pose = load_docked_pose(str(sdf), smiles, charge=0, multiplicity=1)
    conf = molecule.GetConformer()
    rows = ["0 1"]
    for atom in molecule.GetAtoms():
        point = conf.GetAtomPosition(atom.GetIdx())
        rows.append(f"{atom.GetSymbol()} {point.x:.12f} {point.y:.12f} {point.z:.12f}")
    rows.append("units angstrom")

    carbon = next(index for index, row in enumerate(rows) if row.startswith("C "))
    oxygen = next(index for index, row in enumerate(rows) if row.startswith("O "))
    rows[carbon], rows[oxygen] = rows[oxygen], rows[carbon]
    with pytest.raises(ValueError, match="element order"):
        compute_strain_and_rmsd("\n".join(rows), smiles, pose["mol"])
