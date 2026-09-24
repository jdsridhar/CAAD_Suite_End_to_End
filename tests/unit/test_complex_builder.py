"""Scientific and format checks for coordinate-only protein-ligand assembly."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError
from rdkit import Chem
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.adapters.structure_preparation.complex_builder import CoordinateComplexBuilderHandler
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.docking import DockingResult, DockingRun, DockingScore, Pose
from caddsuite.contracts.registry import CompoundForm, CompoundFormKind
from caddsuite.contracts.structure import PreparedReceptor, Structure, StructureSource
from caddsuite.domain.enums import SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.structure.complex_builder import (
    ComplexBuildError,
    ComplexBuildPolicy,
    assemble_complex_pdb,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/data/golden/docking_g1"


def _fixture():
    expected = json.loads((GOLDEN / "expected.json").read_text())
    details = expected["ligands"]["RC8__5NIU"]
    standardized = standardize_smiles(details["standardized_smiles"])
    project_id = new_ulid()
    compound = make_compound(
        standardized,
        compound_id=new_ulid(),
        project_id=project_id,
        accession="CMP0001",
        name="RC8 fixture",
        original_text=details["raw_smiles"],
        source="legacy_import",
    )
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound.id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=standardized.identity.canonical_smiles,
        formal_charge=standardized.identity.formal_charge,
    )
    structure = Structure(
        id=new_ulid(),
        target_id=new_ulid(),
        source=StructureSource.RCSB,
        source_id="5NIU",
        raw=ArtifactRef(artifact_id=new_ulid(), role="source", sha256="a" * 64),
    )
    receptor_pdb = (
        "\n".join(
            line
            for line in (GOLDEN / "results/RC8__5NIU_complex.pdb").read_text().splitlines()
            if line.startswith("ATOM  ")
        ).encode()
        + b"\n"
    )
    receptor_digest = hashlib.sha256(receptor_pdb).hexdigest()
    receptor = PreparedReceptor(
        id=new_ulid(),
        structure_id=structure.id,
        protocol=SoftwareRef(name="PDBFixer", version="1.12.0", kind=SoftwareKind.LIBRARY),
        ph=7.4,
        protonation_method="fixture",
        artifacts={
            "prepared_structure_pdb": ArtifactRef(
                artifact_id=new_ulid(), role="prepared_structure_pdb", sha256=receptor_digest
            )
        },
    )
    sdf = (GOLDEN / "ligands/RC8__5NIU.sdf").read_bytes()
    sdf_digest = hashlib.sha256(sdf).hexdigest()
    pose_id = new_ulid()
    run_id = new_ulid()
    pose = Pose(
        id=pose_id,
        accession="CMP0001_POSE_001",
        run_id=run_id,
        rank=1,
        score=DockingScore(value=-8.0, scoring_function="vina"),
        structure=ArtifactRef(
            artifact_id=new_ulid(), role="normalized_pose_sdf", sha256=sdf_digest
        ),
        raw=ArtifactRef(artifact_id=new_ulid(), role="raw_pose", sha256="b" * 64),
        fidelity_max_dev_A=0.001,
    )
    docking = DockingResult(
        run=DockingRun(
            id=run_id,
            accession="CMP0001_DOCK_001",
            form_id=form.id,
            conformer_id=new_ulid(),
            receptor_id=receptor.id,
            site_id=new_ulid(),
            engine=SoftwareRef(name="Vina", version="test", kind=SoftwareKind.ENGINE),
            adapter=SoftwareRef(name="caddsuite.vina", version="test", kind=SoftwareKind.ADAPTER),
            params={"site_method": "coordinates"},
            seed=42,
            pose_ids=(pose_id,),
        ),
        poses=(pose,),
    )
    return compound, form, structure, receptor, docking, pose, receptor_pdb, sdf


def test_coordinate_assembly_preserves_pose_graph_and_hydrogen_atoms() -> None:
    compound, form, structure, receptor, docking, pose, receptor_pdb, sdf = _fixture()
    assembly = assemble_complex_pdb(
        prepared_receptor_pdb=receptor_pdb,
        pose_sdf=sdf,
        compound=compound,
        form=form,
        structure=structure,
        receptor=receptor,
        docking=docking,
        pose=pose,
    )
    lines = assembly.pdb_bytes.decode().splitlines()
    protein = [line for line in lines if line.startswith("ATOM  ")]
    ligand = [line for line in lines if line.startswith("HETATM") and line[17:20] == "LIG"]
    source_mol = next(
        iter(Chem.ForwardSDMolSupplier(__import__("io").BytesIO(sdf), removeHs=False))
    )
    assert assembly.protein_atom_count == len(protein) > 0
    assert assembly.ligand_atom_count == len(ligand) == source_mol.GetNumAtoms()
    assert assembly.ligand_heavy_atom_count == compound.parent.heavy_atom_count
    assert sum(line[76:78].strip() == "H" for line in ligand) > 0
    assert assembly.chain_id not in {line[21] for line in protein}
    assert lines[-1] == "END"
    assert all(len(line) >= 78 for line in ligand)
    assert all(line[21] == assembly.chain_id for line in lines if line.startswith("TER   "))
    assert assembly.coordinate_fidelity_max_dev_A <= 0.001
    sdf_conf = source_mol.GetConformer()
    for index, line in enumerate(ligand):
        expected_xyz = sdf_conf.GetAtomPosition(index)
        observed_xyz = tuple(float(line[start : start + 8]) for start in (30, 38, 46))
        assert observed_xyz == pytest.approx(
            (expected_xyz.x, expected_xyz.y, expected_xyz.z), abs=0.00051
        )


def test_assembly_keeps_receptor_heterogens_and_hydrogens() -> None:
    compound, form, structure, receptor, docking, pose, receptor_pdb, sdf = _fixture()
    base = receptor_pdb.decode().splitlines()
    protein_h = "ATOM   9998  H   ALA A   1       1.000   2.000   3.000  1.00  0.00           H"
    water = "HETATM 9999  O   HOH A   2       2.000   3.000   4.000  1.00  0.00           O"
    receptor_pdb = ("\n".join([protein_h, *base, water]) + "\n").encode()
    receptor = receptor.model_copy(
        update={
            "artifacts": {
                "prepared_structure_pdb": receptor.artifacts["prepared_structure_pdb"].model_copy(
                    update={"sha256": hashlib.sha256(receptor_pdb).hexdigest()}
                )
            }
        }
    )
    assembly = assemble_complex_pdb(
        prepared_receptor_pdb=receptor_pdb,
        pose_sdf=sdf,
        compound=compound,
        form=form,
        structure=structure,
        receptor=receptor,
        docking=docking,
        pose=pose,
    )
    output = assembly.pdb_bytes.decode().splitlines()
    assert any(line.startswith("ATOM  ") and line[76:78].strip() == "H" for line in output)
    assert any(line.startswith("HETATM") and line[17:20] == "HOH" for line in output)
    assert assembly.protein_atom_count == len(base) + 2


def test_assembly_rejects_wrong_artifact_digest_and_wrong_form() -> None:
    compound, form, structure, receptor, docking, pose, receptor_pdb, sdf = _fixture()
    with pytest.raises(ComplexBuildError, match="SHA-256"):
        assemble_complex_pdb(
            prepared_receptor_pdb=receptor_pdb + b"# changed\n",
            pose_sdf=sdf,
            compound=compound,
            form=form,
            structure=structure,
            receptor=receptor,
            docking=docking,
            pose=pose,
        )
    wrong_form = form.model_copy(update={"smiles": "CCO"})
    with pytest.raises(ComplexBuildError, match=r"different compound form|graph/stereochemistry"):
        assemble_complex_pdb(
            prepared_receptor_pdb=receptor_pdb,
            pose_sdf=sdf,
            compound=compound,
            form=wrong_form,
            structure=structure,
            receptor=receptor,
            docking=docking,
            pose=pose,
        )


def test_assembly_rejects_formal_charge_mismatch() -> None:
    compound, form, structure, receptor, docking, pose, receptor_pdb, sdf = _fixture()
    charged_form = form.model_copy(update={"formal_charge": form.formal_charge + 1})
    with pytest.raises(ComplexBuildError, match="formal charge"):
        assemble_complex_pdb(
            prepared_receptor_pdb=receptor_pdb,
            pose_sdf=sdf,
            compound=compound,
            form=charged_form,
            structure=structure,
            receptor=receptor,
            docking=docking.model_copy(
                update={"run": docking.run.model_copy(update={"form_id": charged_form.id})}
            ),
            pose=pose,
        )


def test_policy_rejects_unrecorded_pdb_residue_name() -> None:
    with pytest.raises(ValidationError, match="ligand_resname"):
        ComplexBuildPolicy(ligand_resname="TOOLONG")


def test_workflow_handler_returns_registered_complex_contract(tmp_path: Path) -> None:
    compound, form, structure, receptor, docking, pose, receptor_pdb, sdf = _fixture()
    database = tmp_path / "platform.sqlite"
    upgrade(database)
    engine = create_db_engine(database)
    sessions: sessionmaker[Session] = make_session_factory(engine)
    store = ArtifactStore(tmp_path / "artifacts")
    receptor_blob = store.put_bytes(receptor_pdb)
    pose_blob = store.put_bytes(sdf)
    with sessions.begin() as session:
        receptor_row = register_blob(
            session, receptor_blob, kind="prepared_receptor_pdb", media_type="chemical/x-pdb"
        )
        pose_row = register_blob(
            session, pose_blob, kind="normalized_pose_sdf", media_type="chemical/x-mdl-sdfile"
        )
    receptor = receptor.model_copy(
        update={
            "artifacts": {
                "prepared_structure_pdb": ArtifactRef(
                    artifact_id=receptor_row.id,
                    role="prepared_structure_pdb",
                    sha256=receptor_blob.sha256,
                )
            }
        }
    )
    pose = pose.model_copy(
        update={
            "structure": ArtifactRef(
                artifact_id=pose_row.id, role="normalized_pose_sdf", sha256=pose_blob.sha256
            )
        }
    )
    docking = docking.model_copy(update={"poses": (pose,)})
    handler = CoordinateComplexBuilderHandler(artifact_store=store, sessions=sessions)
    invocation = type(
        "Invocation",
        (),
        {
            "task": type("Task", (), {"stage_id": "complex", "params": {}})(),
            "inputs": {
                "compound": (compound,),
                "form": (form,),
                "target_structure": (structure,),
                "receptor": (receptor,),
                "docking": (docking,),
                "pose": (pose,),
            },
        },
    )()
    try:
        result = handler.execute(invocation)
        assert isinstance(result, Complex)
        assert result.compound_id == compound.id
        assert result.form_id == form.id
        assert result.pose_id == pose.id
        assert result.parameters["md_ready"] is False
        assert store.verify(result.assembled.sha256 or "")
        assert store.path_for(result.assembled.sha256 or "").read_bytes().endswith(b"END\n")
        assert result.ligand_heavy_atom_count == compound.parent.heavy_atom_count
    finally:
        engine.dispose()


def test_assembly_preserves_and_remaps_protein_connectivity_records() -> None:
    compound, form, structure, receptor, docking, pose, receptor_pdb, sdf = _fixture()
    atoms = [line for line in receptor_pdb.decode().splitlines() if line.startswith("ATOM  ")]
    first_serial = int(atoms[0][6:11])
    second_serial = int(atoms[1][6:11])
    receptor_pdb += f"CONECT{first_serial:5d}{second_serial:5d}\n".encode()
    receptor = receptor.model_copy(
        update={
            "artifacts": {
                "prepared_structure_pdb": receptor.artifacts["prepared_structure_pdb"].model_copy(
                    update={"sha256": hashlib.sha256(receptor_pdb).hexdigest()}
                )
            }
        }
    )
    assembly = assemble_complex_pdb(
        prepared_receptor_pdb=receptor_pdb,
        pose_sdf=sdf,
        compound=compound,
        form=form,
        structure=structure,
        receptor=receptor,
        docking=docking,
        pose=pose,
    )
    atom_records = [
        line
        for line in assembly.pdb_bytes.decode().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    first_mapped = int(atom_records[0][6:11])
    second_mapped = int(atom_records[1][6:11])
    conect = next(
        line for line in assembly.pdb_bytes.decode().splitlines() if line.startswith("CONECT")
    )
    assert int(conect[6:11]) == first_mapped
    assert int(conect[11:16]) == second_mapped


def test_complex_builder_reproduces_legacy_golden_docked_coordinates() -> None:
    compound, form, structure, receptor, docking, pose, receptor_pdb, _seed_sdf = _fixture()
    legacy_lines = [
        line
        for line in (GOLDEN / "results/RC8__5NIU_complex.pdb").read_text().splitlines()
        if line.startswith("HETATM") and line[17:20] == "LIG"
    ]
    template = Chem.MolFromSmiles(form.smiles)
    assert template is not None
    ligand = Chem.AddHs(template)
    assert ligand.GetNumAtoms() == len(legacy_lines)
    conformer = Chem.Conformer(ligand.GetNumAtoms())
    for index, line in enumerate(legacy_lines):
        assert line[76:78].strip().upper() == ligand.GetAtomWithIdx(index).GetSymbol().upper()
        conformer.SetAtomPosition(
            index,
            tuple(float(line[start : start + 8]) for start in (30, 38, 46)),
        )
    ligand.AddConformer(conformer, assignId=True)
    pose_sdf = (Chem.MolToMolBlock(ligand) + "$$$$\n").encode()
    pose = pose.model_copy(
        update={
            "structure": pose.structure.model_copy(
                update={"sha256": hashlib.sha256(pose_sdf).hexdigest()}
            )
        }
    )
    docking = docking.model_copy(update={"poses": (pose,)})
    assembly = assemble_complex_pdb(
        prepared_receptor_pdb=receptor_pdb,
        pose_sdf=pose_sdf,
        compound=compound,
        form=form,
        structure=structure,
        receptor=receptor,
        docking=docking,
        pose=pose,
    )
    actual = Counter(
        tuple(round(float(line[start : start + 8]), 3) for start in (30, 38, 46))
        for line in assembly.pdb_bytes.decode().splitlines()
        if line.startswith("HETATM")
        and line[17:20] == "LIG"
        and line[76:78].strip().upper() not in {"H", "D"}
    )
    expected = Counter(
        tuple(round(float(line[start : start + 8]), 3) for start in (30, 38, 46))
        for line in legacy_lines
        if line[76:78].strip().upper() not in {"H", "D"}
    )
    assert actual == expected
    assert assembly.ligand_heavy_atom_count == compound.parent.heavy_atom_count
