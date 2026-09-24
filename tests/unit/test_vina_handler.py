"""Small real-engine docking integration for the Vina→Meeko adapter boundary."""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from caddsuite.adapters.docking.vina_handler import VinaDockingHandler
from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.registry import (
    ChemicalIdentity,
    Compound,
    CompoundForm,
    CompoundFormKind,
    Conformer,
    InputRecord,
    StandardizationRecord,
    StandardizationStep,
)
from caddsuite.contracts.structure import (
    BindingSite,
    BindingSiteMethod,
    Structure,
    StructureSource,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import ProjectRow

ROOT = Path(__file__).resolve().parents[2]
FIXER_PYTHON = os.environ.get("CADDSUITE_PDBFIXER_PYTHON")
pytestmark = pytest.mark.skipif(
    not FIXER_PYTHON,
    reason="set CADDSUITE_PDBFIXER_PYTHON to run the real Vina/Meeko stage integration",
)


def test_vina_handler_executes_and_registers_normalized_pose_graph(tmp_path: Path) -> None:
    assert FIXER_PYTHON is not None
    engine_dir = Path(FIXER_PYTHON).resolve().parent
    vina = engine_dir / "vina"
    meeko_python = Path(FIXER_PYTHON)
    vina_version = subprocess.run(
        [str(vina), "--version"], capture_output=True, text=True, check=True, timeout=20
    ).stdout.strip()
    meeko_version = subprocess.run(
        [
            str(meeko_python),
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('meeko'))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout.strip()

    db_path = tmp_path / "platform.sqlite"
    upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    store = ArtifactStore(tmp_path / "artifact-store")
    project_id = new_ulid()
    with sessions.begin() as session:
        session.add(ProjectRow(id=project_id, slug="vina-fixture", name="Vina fixture"))

    receptor_blob = store.put_file(ROOT / "tests/data/golden/structure_g1/5NIU.cif")
    with sessions.begin() as session:
        receptor_row = register_blob(
            session,
            receptor_blob,
            kind="raw_structure_mmcif",
            media_type="chemical/x-mmcif",
            original_name="5NIU.cif",
        )
        receptor_artifact_id = receptor_row.id
    target_id = new_ulid()
    structure = Structure(
        id=new_ulid(),
        target_id=target_id,
        source=StructureSource.RCSB,
        source_id="5NIU",
        entity_sequences={"1": "fixture sequence"},
        raw=ArtifactRef(
            artifact_id=receptor_artifact_id,
            role="raw_structure_mmcif",
            sha256=receptor_blob.sha256,
        ),
    )
    fixer_handler = PDBFixerPreparationHandler(
        python_executable=meeko_python,
        worker_script=ROOT / "src/caddsuite_worker/pdbfixer_worker.py",
        work_root=tmp_path / "prepare-jobs",
        log_root=tmp_path / "prepare-logs",
        engine_version="PDBFixer 1.12.0 / OpenMM 8.4",
        executor=LocalExecutor(store, sessions),
        artifact_store=store,
        sessions=sessions,
    )
    prepared = fixer_handler.execute(
        SimpleNamespace(
            task=SimpleNamespace(
                stage_id="prepare_protein", params={"selected_chain_ids": ["A"], "ph": 7.4}
            ),
            inputs={"structure": (structure,)},
        )
    )

    ligand_path = ROOT / "tests/data/golden/docking_g1/ligands/RC8__5NIU.sdf"
    mols = [mol for mol in Chem.SDMolSupplier(str(ligand_path), removeHs=False) if mol]
    assert len(mols) == 1
    parent_mol = Chem.RemoveHs(mols[0])
    canonical_smiles = Chem.MolToSmiles(parent_mol, canonical=True, isomericSmiles=True)
    inchi = Chem.MolToInchi(parent_mol)
    ligand_blob = store.put_file(ligand_path)
    with sessions.begin() as session:
        ligand_row = register_blob(
            session,
            ligand_blob,
            kind="ligand_conformer_sdf",
            media_type="chemical/x-mdl-sdfile",
            original_name=ligand_path.name,
        )
        ligand_artifact_id = ligand_row.id
    compound_id = new_ulid()
    compound = Compound(
        id=compound_id,
        accession="CMP0001",
        project_id=project_id,
        name="RC8 fixture",
        input_record=InputRecord(source="legacy_import", original_text=canonical_smiles),
        parent=ChemicalIdentity(
            canonical_smiles=canonical_smiles,
            inchi=inchi,
            inchikey=Chem.MolToInchiKey(parent_mol),
            formula=rdMolDescriptors.CalcMolFormula(parent_mol),
            formal_charge=Chem.GetFormalCharge(parent_mol),
            heavy_atom_count=parent_mol.GetNumHeavyAtoms(),
        ),
        standardization=StandardizationRecord(
            policy="curated_golden_fixture",
            steps=(StandardizationStep(operation="fixture_selection", changed=False),),
            toolkit=SoftwareRef(
                name="RDKit",
                version=importlib.metadata.version("rdkit"),
                kind=SoftwareKind.LIBRARY,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
        ),
    )
    form = CompoundForm(
        id=new_ulid(),
        compound_id=compound_id,
        kind=CompoundFormKind.PARENT_NEUTRAL,
        smiles=canonical_smiles,
        formal_charge=Chem.GetFormalCharge(parent_mol),
    )
    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        compound_id=compound_id,
        generator="curated_fixture",
        selected_by="golden_docking_fixture",
        structure=ArtifactRef(
            artifact_id=ligand_artifact_id,
            role="ligand_conformer_sdf",
            sha256=ligand_blob.sha256,
        ),
    )
    site = BindingSite(
        id=new_ulid(),
        target_id=target_id,
        method=BindingSiteMethod.COORDINATES,
        center_A=(6.2435, 13.235, 189.6215),
        size_A=(28.341, 22.0, 22.0),
        source_structure=structure.raw,
    )
    handler = VinaDockingHandler(
        vina_executable=vina,
        meeko_python=meeko_python,
        mk_prepare_receptor=engine_dir / "mk_prepare_receptor.py",
        mk_prepare_ligand=engine_dir / "mk_prepare_ligand.py",
        mk_export=engine_dir / "mk_export.py",
        vina_version=vina_version,
        meeko_version=meeko_version,
        work_root=tmp_path / "docking-jobs",
        log_root=tmp_path / "docking-logs",
        executor=LocalExecutor(store, sessions),
        artifact_store=store,
        sessions=sessions,
    )
    try:
        result = handler.execute(
            SimpleNamespace(
                task=SimpleNamespace(
                    stage_id="dock",
                    params={
                        "exhaustiveness": 1,
                        "num_modes": 2,
                        "energy_range_kcal_mol": 3.0,
                        "cpu_cores": 2,
                        "seed": 42,
                    },
                ),
                inputs={
                    "compound": (compound,),
                    "form": (form,),
                    "conformer": (conformer,),
                    "receptor": (prepared,),
                    "target_structure": (structure,),
                    "site": (site,),
                },
            )
        )
        assert result.run.seed == 42
        assert 1 <= len(result.poses) <= 2
        assert result.run.pose_ids == tuple(pose.id for pose in result.poses)
        assert all(store.verify(pose.structure.sha256 or "") for pose in result.poses)
        assert all(store.verify(pose.raw.sha256 or "") for pose in result.poses)
        assert all(pose.fidelity_max_dev_A <= 0.005 for pose in result.poses)
        assert store.verify(result.artifacts["vina_poses_pdbqt"].sha256 or "")
        assert store.verify(result.artifacts["vina_stdout"].sha256 or "")
    finally:
        engine.dispose()
