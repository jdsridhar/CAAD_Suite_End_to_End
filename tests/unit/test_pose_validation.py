"""Geometry and chemistry guards for docking-pose system preparation."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.domain.identity import new_ulid
from caddsuite.structure.pose_validation import validate_pose_for_system_build


def molecule(smiles: str, *, add_hydrogens: bool = True) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    if add_hydrogens:
        mol = Chem.AddHs(mol)
    assert AllChem.EmbedMolecule(mol, randomSeed=31) == 0
    return mol


def sdf_bytes(mol: Chem.Mol) -> bytes:
    return Chem.MolToMolBlock(mol).encode("utf-8")


def system_identity(smiles: str):
    standardized = standardize_smiles(smiles)
    compound = make_compound(
        standardized,
        compound_id=new_ulid(),
        project_id=new_ulid(),
        accession="CMP0001",
        name="test",
        original_text=smiles,
        source="manual",
    )
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound.id,
        kind=CompoundFormKind.USER_SUPPLIED,
        smiles=smiles,
        formal_charge=standardized.identity.formal_charge,
    )
    return compound, form


def receptor_atom_at(x: float, y: float, z: float) -> bytes:
    line = (
        f"ATOM  {1:5d}  C   ALA A   1    {x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{20.0:6.2f}          C  "
    )
    return (line + "\nEND\n").encode("ascii")


def test_pose_graph_and_hydrogen_completeness_are_checked():
    smiles = "CC(=O)Oc1ccccc1C(=O)O"
    compound, form = system_identity(smiles)
    missing_h = molecule(smiles, add_hydrogens=False)
    issues = validate_pose_for_system_build(
        compound=compound, form=form, pose_sdf=sdf_bytes(missing_h)
    )
    assert "POSE.HYDROGEN_COUNT_MISMATCH" in {issue.code for issue in issues}
    assert "POSE.CLASH_NOT_ASSESSED" in {issue.code for issue in issues}


def test_pose_stereochemistry_is_compared_to_selected_form():
    smiles = "C[C@@H](C(=O)O)N"
    inverse = "C[C@H](C(=O)O)N"
    compound, form = system_identity(smiles)
    issues = validate_pose_for_system_build(
        compound=compound, form=form, pose_sdf=sdf_bytes(molecule(inverse))
    )
    assert "POSE.GRAPH_OR_STEREOCHEMISTRY_MISMATCH" in {issue.code for issue in issues}


def test_severe_receptor_overlap_blocks_system_build_and_reports_distance():
    smiles = "CCO"
    compound, form = system_identity(smiles)
    pose = molecule(smiles)
    point = pose.GetConformer().GetAtomPosition(0)
    issues = validate_pose_for_system_build(
        compound=compound,
        form=form,
        pose_sdf=sdf_bytes(pose),
        receptor_pdb=receptor_atom_at(point.x, point.y, point.z),
    )
    severe = [issue for issue in issues if issue.code == "POSE.SEVERE_RECEPTOR_CLASH"]
    assert len(severe) == 1
    assert severe[0].severity.value == "blocker"
    assert severe[0].evidence["minimum_heavy_atom_distance_A"] < 0.001


def test_spatially_separated_pose_has_no_clash_issue():
    smiles = "CCO"
    compound, form = system_identity(smiles)
    issues = validate_pose_for_system_build(
        compound=compound,
        form=form,
        pose_sdf=sdf_bytes(molecule(smiles)),
        receptor_pdb=receptor_atom_at(100.0, 100.0, 100.0),
    )
    assert not any("CLASH" in issue.code or "CONTACT" in issue.code for issue in issues)
