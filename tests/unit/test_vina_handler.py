"""Engine integration for Vina, AutoDock4, complex assembly, and 8YZ redocking."""

from __future__ import annotations

import importlib.metadata
import math
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdkit import Chem
from rdkit.Chem import rdMolAlign, rdMolDescriptors

from caddsuite.adapters.docking.autodock4_handler import AutoDock4DockingHandler
from caddsuite.adapters.docking.vina_handler import VinaDockingHandler
from caddsuite.adapters.structure_preparation.complex_builder import CoordinateComplexBuilderHandler
from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.report_builder import build_provenance_report
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.docking import DockingResult
from caddsuite.contracts.execution import TaskAttempt
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
from caddsuite.contracts.reporting import ReportSectionName, ReportSectionStatus
from caddsuite.contracts.structure import (
    BindingSite,
    BindingSiteMethod,
    LigandReference,
    Structure,
    StructureSource,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.reporting.renderers import render_report
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, WorkflowRunRow
from caddsuite.storage.provenance_graph import attempt_lineage
from caddsuite.workflow.definition import WorkflowDefinition

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

    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "Vina runtime integration",
            "inputs": {
                "compound": {"contract": "compound/1.0"},
                "form": {"contract": "compound_form/1.0"},
                "conformer": {"contract": "conformer/1.1"},
                "receptor": {"contract": "prepared_receptor/1.0"},
                "target_structure": {"contract": "structure/1.0"},
                "site": {"contract": "binding_site/1.0"},
            },
            "stages": [
                {
                    "id": "dock",
                    "kind": "docking",
                    "engine": "vina",
                    "for_each": "compound",
                    "input_contracts": {
                        "compound": "compound/1.0",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                        "receptor": "prepared_receptor/1.0",
                        "target_structure": "structure/1.0",
                        "site": "binding_site/1.0",
                    },
                    "input_bindings": {
                        "compound": "$compound",
                        "form": "$form",
                        "conformer": "$conformer",
                        "receptor": "$receptor",
                        "target_structure": "$target_structure",
                        "site": "$site",
                    },
                    "output_contract": DockingResult.schema_id(),
                    "params": {
                        "engine_parameters": {
                            "vina_executable": str(vina),
                            "meeko_python": str(meeko_python),
                            "mk_prepare_receptor": str(engine_dir / "mk_prepare_receptor.py"),
                            "mk_prepare_ligand": str(engine_dir / "mk_prepare_ligand.py"),
                            "mk_export": str(engine_dir / "mk_export.py"),
                            "memory_MiB": 2048,
                        },
                        "docking_parameters": {
                            "exhaustiveness": 1,
                            "num_modes": 2,
                            "energy_range_kcal_mol": 3.0,
                            "cpu_cores": 2,
                            "seed": 42,
                        },
                    },
                }
            ],
            "outputs": {"result": "dock"},
        }
    )
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    runtime = LocalWorkflowRuntime.open(
        data_root=tmp_path / "platform",
        handlers=lambda services: registry.build_handlers(workflow, services),
    )
    engine = runtime.engine
    sessions = runtime.sessions
    store = runtime.services.artifacts
    project_id = new_ulid()
    with sessions.begin() as session:
        project = ProjectRow(id=project_id, slug="vina-fixture", name="Vina fixture")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project_id,
            accession="RUN-VINA-001",
            workflow_hash="c" * 64,
            config_hash="d" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id

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
        executor=runtime.services.executor,
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
        executor=runtime.services.executor,
        artifact_store=store,
        sessions=sessions,
    )
    try:
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={
                "compound": (compound,),
                "form": (form,),
                "conformer": (conformer,),
                "receptor": (prepared,),
                "target_structure": (structure,),
                "site": (site,),
            },
        )
        assert not outcome.failures
        result = outcome.outputs["result"][0].value
        assert isinstance(result, DockingResult)
        with sessions() as session:
            attempt_row = session.query(TaskAttemptRow).one()
        attempt = TaskAttempt.model_validate(attempt_row.payload)
        assert attempt.status.value == "succeeded"
        assert attempt.resources is not None
        assert attempt.resources.cpu_cores == 2
        assert len(attempt.steps) == 4
        assert {step.exit_code for step in attempt.steps} == {0}
        assert any(
            item.role == "engine" and item.software.version == vina_version
            for item in attempt.software
        )
        assert any(edge.direction == "generated" for edge in attempt.artifacts)
        graph = attempt_lineage(sessions, str(attempt.id))
        assert graph["root_attempt_id"] == str(attempt.id)
        assert [item["id"] for item in graph["attempts"]] == [str(attempt.id)]
        assert {edge["direction"] for edge in graph["edges"]} == {"used", "generated"}
        assert all(item["sha256"] for item in graph["artifacts"])
        assert all(store.verify(item["sha256"]) for item in graph["artifacts"])
        assert len([step for step in attempt.steps if step.exit_code == 0]) == 4
        report = build_provenance_report(
            project_id=project_id,
            title="5NIU RC8 docking demonstration",
            provenance_graph=graph,
            result_sections={ReportSectionName.DOCKING_RESULTS: result.model_dump(mode="json")},
        )
        report_files = render_report(report, ("html", "json", "csv", "pdf"))
        assert set(report_files) == {"html", "json", "csv", "pdf"}
        report_sections = {section.name: section for section in report.sections}
        assert (
            report_sections[ReportSectionName.DOCKING_RESULTS].status
            is ReportSectionStatus.AVAILABLE
        )
        assert report_sections[ReportSectionName.MD_METHOD].status is ReportSectionStatus.NOT_RUN
        assert b"computational predictions" in report_files["html"].lower()
        assert report_files["pdf"].startswith(b"%PDF")
        assert result.run.seed == 42
        assert 1 <= len(result.poses) <= 2
        assert result.run.pose_ids == tuple(pose.id for pose in result.poses)
        assert all(store.verify(pose.structure.sha256 or "") for pose in result.poses)
        assert all(store.verify(pose.raw.sha256 or "") for pose in result.poses)
        assert all(pose.fidelity_max_dev_A <= 0.005 for pose in result.poses)
        assert store.verify(result.artifacts["vina_poses_pdbqt"].sha256 or "")
        assert store.verify(result.artifacts["vina_stdout"].sha256 or "")
        complex_handler = CoordinateComplexBuilderHandler(artifact_store=store, sessions=sessions)
        coordinate_complex = complex_handler.execute(
            SimpleNamespace(
                task=SimpleNamespace(stage_id="complex", params={}),
                inputs={
                    "compound": (compound,),
                    "form": (form,),
                    "target_structure": (structure,),
                    "receptor": (prepared,),
                    "docking": (result,),
                    "pose": (result.poses[0],),
                },
            )
        )
        assert coordinate_complex.pose_id == result.poses[0].id
        assert coordinate_complex.ligand_heavy_atom_count == compound.parent.heavy_atom_count
        assert coordinate_complex.parameters["md_ready"] is False
        assert store.verify(coordinate_complex.assembled.sha256 or "")

        ad4_bin_dir = os.environ.get("CADDSUITE_AUTODOCK4_BIN_DIR")
        if ad4_bin_dir:
            ad4_bin = Path(ad4_bin_dir)
            autodock = ad4_bin / "autodock4"
            autogrid = ad4_bin / "autogrid4"
            ad4_version = (
                subprocess.run(
                    [str(autodock), "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=20,
                )
                .stdout.splitlines()[0]
                .strip()
            )
            autogrid_version = (
                subprocess.run(
                    [str(autogrid), "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=20,
                )
                .stdout.splitlines()[0]
                .strip()
            )
            ad4_handler = AutoDock4DockingHandler(
                autodock_executable=autodock,
                autogrid_executable=autogrid,
                meeko_python=meeko_python,
                mk_prepare_receptor=engine_dir / "mk_prepare_receptor.py",
                mk_prepare_ligand=engine_dir / "mk_prepare_ligand.py",
                mk_export=engine_dir / "mk_export.py",
                autodock_version=ad4_version,
                autogrid_version=autogrid_version,
                meeko_version=meeko_version,
                work_root=tmp_path / "autodock4-jobs",
                log_root=tmp_path / "autodock4-logs",
                executor=LocalExecutor(store, sessions),
                artifact_store=store,
                sessions=sessions,
            )
            ad4_result = ad4_handler.execute(
                SimpleNamespace(
                    task=SimpleNamespace(
                        stage_id="dock_ad4",
                        params={
                            "grid": {"npts": [80, 80, 80], "spacing_A": 0.375},
                            "docking": {
                                "seed": [42, 1337],
                                "ga_runs": 2,
                                "ga_pop_size": 10,
                                "ga_num_evals": 1000,
                                "ga_num_generations": 100,
                                "ga_elitism": 1,
                                "ga_mutation_rate": 0.02,
                                "ga_crossover_rate": 0.8,
                                "ga_window_size": 10,
                                "rmsd_threshold_A": 2.0,
                            },
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
            assert ad4_result.run.seed == 42
            assert ad4_result.run.pose_ids == tuple(pose.id for pose in ad4_result.poses)
            assert ad4_result.poses
            assert all(store.verify(pose.structure.sha256 or "") for pose in ad4_result.poses)
            assert all(store.verify(pose.raw.sha256 or "") for pose in ad4_result.poses)
            assert store.verify(ad4_result.artifacts["autodock4_dlg"].sha256 or "")

        # G-DOCK-4: blind-independent, coordinate-frame-preserving Vina redocking of
        # the native 8YZ ligand. The symmetry-aware RMSD is calculated without fitting.
        native_pdb = ROOT / "tests/data/golden/docking_g1/receptors/5NIU_ref_ligand.pdb"
        native_coordinates = Chem.MolFromPDBFile(str(native_pdb), removeHs=False, sanitize=True)
        ideal_path = ROOT / "tests/data/golden/docking_g1/receptors/8YZ_ideal.sdf"
        ideal_molecule = Chem.SDMolSupplier(str(ideal_path), removeHs=False)[0]
        assert native_coordinates is not None
        assert ideal_molecule is not None
        native_coordinates = Chem.RemoveHs(native_coordinates)
        native_parent = Chem.RemoveHs(ideal_molecule)
        cif_lines = (ROOT / "tests/data/golden/structure_g1/5NIU.cif").read_text().splitlines()
        atom_loop_start = next(
            index
            for index, line in enumerate(cif_lines)
            if line.strip() == "_chem_comp_atom.comp_id"
        )
        ccd_heavy_names = []
        for line in cif_lines[atom_loop_start + 5 :]:
            fields = line.split()
            if not fields or line.startswith("#"):
                break
            if fields[0] == "8YZ" and fields[2] != "H":
                ccd_heavy_names.append(fields[1])
        pdb_atom_lines = [
            line
            for line in native_pdb.read_text().splitlines()
            if line.startswith(("ATOM", "HETATM"))
        ]
        pdb_atom_names = [line[12:16].strip() for line in pdb_atom_lines]
        assert pdb_atom_names == ccd_heavy_names
        assert tuple(atom.GetAtomicNum() for atom in native_coordinates.GetAtoms()) == tuple(
            atom.GetAtomicNum() for atom in native_parent.GetAtoms()
        )
        native_conformer_coords = native_coordinates.GetConformer()
        ideal_conformer = native_parent.GetConformer()
        for atom_index in range(native_parent.GetNumAtoms()):
            ideal_conformer.SetAtomPosition(
                atom_index, native_conformer_coords.GetAtomPosition(atom_index)
            )
        native_smiles = Chem.MolToSmiles(native_parent, canonical=True, isomericSmiles=True)
        native_inchi = Chem.MolToInchi(native_parent)
        native_sdf = tmp_path / "native_8yz.sdf"
        native_ligand = Chem.AddHs(native_parent, addCoords=True)
        with Chem.SDWriter(str(native_sdf)) as writer:
            writer.write(native_ligand)
        native_blob = store.put_file(native_sdf)
        with sessions.begin() as session:
            native_row = register_blob(
                session,
                native_blob,
                kind="ligand_conformer_sdf",
                media_type="chemical/x-mdl-sdfile",
                original_name="native_8yz.sdf",
            )
            native_artifact_id = native_row.id
        native_compound_id = new_ulid()
        native_compound = Compound(
            id=native_compound_id,
            accession="CMP0002",
            project_id=project_id,
            name="Native 8YZ redocking fixture",
            input_record=InputRecord(source="legacy_import", original_text=native_smiles),
            parent=ChemicalIdentity(
                canonical_smiles=native_smiles,
                inchi=native_inchi,
                inchikey=Chem.MolToInchiKey(native_parent),
                formula=rdMolDescriptors.CalcMolFormula(native_parent),
                formal_charge=Chem.GetFormalCharge(native_parent),
                heavy_atom_count=native_parent.GetNumHeavyAtoms(),
            ),
            standardization=StandardizationRecord(
                policy="native_reference_ligand",
                steps=(StandardizationStep(operation="PDB_graph_perception", changed=False),),
                toolkit=SoftwareRef(
                    name="RDKit",
                    version=importlib.metadata.version("rdkit"),
                    kind=SoftwareKind.LIBRARY,
                    license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
                ),
            ),
        )
        native_form = CompoundForm(
            id=new_ulid(),
            compound_id=native_compound_id,
            kind=CompoundFormKind.PARENT_NEUTRAL,
            smiles=native_smiles,
            formal_charge=Chem.GetFormalCharge(native_parent),
        )
        native_conformer = Conformer(
            id=new_ulid(),
            form_id=native_form.id,
            compound_id=native_compound_id,
            generator="native_crystal_coordinates_with_RDKit_hydrogens",
            selected_by="G-DOCK-4",
            structure=ArtifactRef(
                artifact_id=native_artifact_id,
                role="ligand_conformer_sdf",
                sha256=native_blob.sha256,
            ),
        )
        native_site = BindingSite(
            id=new_ulid(),
            target_id=target_id,
            method=BindingSiteMethod.REFERENCE_LIGAND,
            reference=LigandReference(resname="8YZ", chain="A", resseq="201", copies_found=2),
            center_A=(6.2435, 13.235, 189.6215),
            size_A=(28.341, 22.0, 22.0),
            source_structure=structure.raw,
        )
        redock = handler.execute(
            SimpleNamespace(
                task=SimpleNamespace(
                    stage_id="redock_native_8yz",
                    params={
                        "exhaustiveness": 16,
                        "num_modes": 9,
                        "energy_range_kcal_mol": 3.0,
                        "cpu_cores": 2,
                        "seed": 42,
                    },
                ),
                inputs={
                    "compound": (native_compound,),
                    "form": (native_form,),
                    "conformer": (native_conformer,),
                    "receptor": (prepared,),
                    "target_structure": (structure,),
                    "site": (native_site,),
                },
            )
        )
        redocked_molecules = [
            mol
            for pose in redock.poses
            if (
                mol := Chem.MolFromMolFile(
                    str(store.path_for(pose.structure.sha256 or "")),
                    removeHs=False,
                    sanitize=True,
                )
            )
            is not None
        ]
        assert len(redocked_molecules) == len(redock.poses)
        native_heavy = Chem.RemoveHs(native_parent)
        pose_rmsds_A = tuple(
            rdMolAlign.CalcRMS(Chem.RemoveHs(molecule), native_heavy, maxMatches=10000)
            for molecule in redocked_molecules
        )
        print(
            "G-DOCK-4",
            {
                "engine": vina_version,
                "seed": redock.run.seed,
                "exhaustiveness": redock.run.params["exhaustiveness"],
                "poses_rank_score_rmsd_A": tuple(
                    (pose.rank, pose.score.value, round(rmsd, 4))
                    for pose, rmsd in zip(redock.poses, pose_rmsds_A, strict=True)
                ),
                "target_A": 2.0,
            },
        )
        assert redock.run.seed == 42
        assert all(math.isfinite(rmsd) for rmsd in pose_rmsds_A)
    finally:
        engine.dispose()
