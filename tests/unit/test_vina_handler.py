"""Engine integration for Vina, AutoDock4, complex assembly, and 8YZ redocking."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

from caddsuite.adapters.docking.autodock4_handler import AutoDock4DockingHandler
from caddsuite.adapters.docking.vina_handler import VinaDockingHandler
from caddsuite.adapters.md.openmm import OpenMMMDAdapter
from caddsuite.adapters.structure_preparation.complex_builder import CoordinateComplexBuilderHandler
from caddsuite.adapters.structure_preparation.pdbfixer import PDBFixerPreparationHandler
from caddsuite.adapters.system_builders.amber_handler import AmberTLeapBuilderHandler
from caddsuite.adapters.system_builders.amber_tleap import AmberTLeapBuilderAdapter
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.md_stage_plugin import MDStagePlugin
from caddsuite.application.md_trajectory_binding_stage_plugin import (
    MDOutputTrajectoryBindingHandler,
)
from caddsuite.application.mdanalysis_trajectory_stage_plugin import (
    MDAnalysisTrajectoryStagePlugin,
)
from caddsuite.application.report_builder import build_provenance_report
from caddsuite.application.report_stage_plugin import ReportStagePlugin
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.application.trajectory_stage_plugin import TrajectoryAnalysisStagePlugin
from caddsuite.contracts.analysis import (
    MDOutputTrajectoryPlan,
    TrajectoryAnalysisPlan,
    TrajectoryAnalysisResult,
    TrajectoryMetric,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.docking import DockingResult
from caddsuite.contracts.execution import TaskAttempt
from caddsuite.contracts.md import (
    AtomSelection,
    MDProtocol,
    MDStage,
    MDStageInput,
    MDStageKind,
    MDStageResult,
)
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
from caddsuite.contracts.reporting import ReportBundle, ReportSectionName, ReportSectionStatus
from caddsuite.contracts.structure import (
    BindingSite,
    BindingSiteMethod,
    LigandReference,
    Structure,
    StructureSource,
)
from caddsuite.contracts.system import SystemBuildRequest
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import LocalExecutor
from caddsuite.ports.adapters import AdapterContext
from caddsuite.reporting.renderers import render_report
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, WorkflowRunRow
from caddsuite.storage.provenance_graph import attempt_lineage
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from caddsuite.workflow.scheduler import TaskInvocation

ROOT = Path(__file__).resolve().parents[2]
FIXER_PYTHON = os.environ.get("CADDSUITE_PDBFIXER_PYTHON")
AMBER_HOME = os.environ.get("CADDSUITE_AMBER_HOME")
GROMACS = os.environ.get("CADDSUITE_GROMACS_EXECUTABLE")
OPENMM_PYTHON = os.environ.get("CADDSUITE_OPENMM_PYTHON")
MDA_PYTHON = os.environ.get("CADDSUITE_MDA_PYTHON")
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
                "receptor": {"contract": "prepared_receptor/1.2"},
                "target_structure": {"contract": "structure/1.0"},
                "site": {"contract": "binding_site/1.0"},
            },
            "stages": [
                {
                    "id": "dock",
                    "kind": "docking",
                    "for_each": "compound_form",
                    "engine": "vina",
                    "input_contracts": {
                        "compound": "compound/1.0",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                        "receptor": "prepared_receptor/1.2",
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
    tautomer_molecules = rdMolStandardize.TautomerEnumerator().Enumerate(parent_mol)
    alternate = next(
        molecule
        for molecule in tautomer_molecules
        if Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True) != canonical_smiles
    )
    alternate_smiles = Chem.MolToSmiles(alternate, canonical=True, isomericSmiles=True)
    alternate_form = CompoundForm(
        id=new_ulid(),
        compound_id=compound_id,
        kind=CompoundFormKind.TAUTOMER,
        smiles=alternate_smiles,
        formal_charge=Chem.GetFormalCharge(alternate),
    )
    alternate_3d = Chem.AddHs(Chem.MolFromSmiles(alternate_smiles))
    assert AllChem.EmbedMolecule(alternate_3d, randomSeed=42) == 0
    assert AllChem.MMFFOptimizeMolecule(alternate_3d, maxIters=1000) in {0, 1}
    alternate_sdf = tmp_path / "alternate_tautomer.sdf"
    with Chem.SDWriter(str(alternate_sdf)) as writer:
        writer.write(alternate_3d)
    alternate_blob = store.put_file(alternate_sdf)
    with sessions.begin() as session:
        alternate_row = register_blob(
            session,
            alternate_blob,
            kind="ligand_conformer_sdf",
            media_type="chemical/x-mdl-sdfile",
            original_name=alternate_sdf.name,
        )
        alternate_artifact_id = alternate_row.id
    alternate_conformer = Conformer(
        id=new_ulid(),
        form_id=alternate_form.id,
        compound_id=compound_id,
        generator="RDKit ETKDGv3 + MMFF",
        seed=42,
        structure=ArtifactRef(
            artifact_id=alternate_artifact_id,
            role="ligand_conformer_sdf",
            sha256=alternate_blob.sha256,
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
                "form": (form, alternate_form),
                "conformer": (conformer, alternate_conformer),
                "receptor": (prepared,),
                "target_structure": (structure,),
                "site": (site,),
            },
        )
        assert not outcome.failures
        results = [item.value for item in outcome.outputs["result"]]
        assert len(results) == 2
        assert all(isinstance(item, DockingResult) for item in results)
        results_by_form = {item.run.form_id: item for item in results}
        assert set(results_by_form) == {form.id, alternate_form.id}
        result = results_by_form[form.id]
        assert len({item.run.id for item in results}) == 2
        with sessions() as session:
            attempt_rows = session.query(TaskAttemptRow).all()
        attempts = [TaskAttempt.model_validate(row.payload) for row in attempt_rows]
        assert len(attempts) == 2
        assert all(item.status.value == "succeeded" for item in attempts)
        assert all(item.resources is not None for item in attempts)
        assert all(item.resources.cpu_cores == 2 for item in attempts if item.resources)
        attempt = attempts[0]
        assert attempt.status.value == "succeeded"
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
        assert coordinate_complex.coordinate_fidelity_max_dev_A <= 0.001
        assert coordinate_complex.parameters["md_ready"] is False
        assert store.verify(coordinate_complex.assembled.sha256 or "")

        # Optional, real pose-linked system-builder validation, enabled explicitly.
        if AMBER_HOME and GROMACS:
            protein_ref = coordinate_complex.protein
            ligand_ref = coordinate_complex.ligand
            assert protein_ref.sha256 is not None
            assert ligand_ref.sha256 is not None
            protein_bytes = store.path_for(protein_ref.sha256).read_bytes()
            histidine_atoms: dict[tuple[str, str, str, str], set[str]] = {}
            for line in protein_bytes.decode("ascii").splitlines():
                if not line.startswith(("ATOM  ", "HETATM")):
                    continue
                resname = line[17:20].strip().upper()
                if resname not in {"HIS", "HID", "HIE", "HIP"}:
                    continue
                key = (
                    line[21:22].strip() or "_",
                    line[22:26].strip(),
                    line[26:27].strip() or "_",
                    resname,
                )
                histidine_atoms.setdefault(key, set()).add(line[12:16].strip().upper())
            histidine_states: dict[str, str] = {}
            for (chain, sequence, insertion, resname), atom_names in histidine_atoms.items():
                residue_key = f"{chain}:{sequence}:{insertion}"
                if resname in {"HID", "HIE", "HIP"}:
                    state = resname
                elif "HD1" in atom_names and "HE2" in atom_names:
                    state = "HIP"
                elif "HD1" in atom_names:
                    state = "HID"
                elif "HE2" in atom_names:
                    state = "HIE"
                else:
                    raise AssertionError(
                        f"prepared HIS {residue_key} has no explicit ring proton; "
                        "AmberTools requires a recorded state"
                    )
                histidine_states[residue_key] = state
            system_request = SystemBuildRequest(
                id=new_ulid(),
                complex_id=coordinate_complex.id,
                compound_id=compound.id,
                form_id=form.id,
                target_id=target_id,
                pose_id=result.poses[0].id,
                source_artifacts={
                    "inputs/protein.pdb": protein_ref,
                    "inputs/ligand.sdf": ligand_ref,
                },
                selections={"protein": "Protein", "ligand": "LIG"},
                mode="build",
                parameters={
                    "protein_artifact_path": "inputs/protein.pdb",
                    "ligand_artifact_path": "inputs/ligand.sdf",
                    "protein_ff": "ff14SB",
                    "ligand_method": "GAFF2",
                    "ligand_charge_model": "AM1-BCC",
                    "ligand_net_charge": form.formal_charge,
                    "protein_ph": prepared.ph,
                    "histidine_states": histidine_states,
                    "disulfide_bonds": [["A:40:_", "A:114:_"]],
                    "water_model": "TIP3P",
                    "ion_parameters": "Joung-Cheatham TIP3P",
                    "ion_policy": "neutralize_only",
                    "box_padding_A": 8.0,
                    # Allow an opt-in comparison run to exercise GROMACS conversion on this
                    # same pose-derived complex while keeping native Amber as the default.
                    "output_format": os.environ.get("CADDSUITE_TEST_AMBER_OUTPUT_FORMAT", "amber"),
                },
            )
            amber_adapter = AmberTLeapBuilderAdapter(
                amber_prefix=Path(AMBER_HOME),
                gromacs_executable=Path(GROMACS),
                worker_script=ROOT / "src/caddsuite_worker/amber_tleap_worker.py",
            )
            amber_handler = AmberTLeapBuilderHandler(
                adapter=amber_adapter,
                work_root=tmp_path / "amber-pose-jobs",
                log_root=tmp_path / "amber-pose-logs",
                engine_version="configured AmberTools and GROMACS executables",
                executor=runtime.services.executor,
                artifact_store=store,
                sessions=sessions,
            )
            built_system = amber_handler.execute(
                SimpleNamespace(
                    task=SimpleNamespace(stage_id="amber_pose_build", params={}),
                    inputs={
                        "system_build_request": (system_request,),
                        "complex": (coordinate_complex,),
                    },
                )
            )
            assert built_system.complex_id == coordinate_complex.id
            assert built_system.system.compound_id == compound.id
            assert built_system.system.form_id == form.id
            assert built_system.system.selections["ligand"].n_atoms == (
                coordinate_complex.ligand_atom_count
            )
            assert built_system.system.selections["ligand"].verified
            assert all(
                artifact.sha256 and store.verify(artifact.sha256)
                for artifact in built_system.normalized_artifacts.values()
            )
            build_report_ref = built_system.raw_artifacts["amber_outputs/worker_result.json"]
            assert build_report_ref.sha256 is not None
            build_report = json.loads(
                store.path_for(build_report_ref.sha256).read_text(encoding="utf-8")
            )
            capture_path = os.environ.get("CADDSUITE_TEST_AMBER_REPORT_CAPTURE")
            if capture_path:
                with Path(capture_path).open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(build_report, sort_keys=True, indent=2) + "\n")
            artifact_capture = os.environ.get("CADDSUITE_TEST_AMBER_ARTIFACT_CAPTURE")
            if artifact_capture:
                capture_root = Path(artifact_capture)
                capture_root.mkdir(parents=True, exist_ok=False)
                captured_artifacts: dict[str, str] = {}
                for artifact_name, artifact_ref in built_system.raw_artifacts.items():
                    parts = Path(artifact_name).parts
                    if not parts or parts[0] != "amber_outputs":
                        continue
                    if len(parts) < 2:
                        raise AssertionError(f"invalid worker artifact path: {artifact_name}")
                    relative = Path(*parts[1:])
                    if any(part in {".", ".."} for part in relative.parts):
                        raise AssertionError(f"unsafe raw artifact path: {artifact_name}")
                    if artifact_ref.sha256 is None:
                        raise AssertionError(f"raw artifact has no hash: {artifact_name}")
                    destination = capture_root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(store.path_for(artifact_ref.sha256), destination)
                    captured_artifacts[relative.as_posix()] = artifact_ref.sha256
                (capture_root / "manifest.json").write_text(
                    json.dumps(captured_artifacts, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
            charge_normalization = build_report["ligand_charge_normalization"]
            assert charge_normalization["normalized_charge_sum_e"] == pytest.approx(
                charge_normalization["formal_charge_e"], abs=1e-10
            )
            assert charge_normalization["max_per_atom_charge_change_e"] <= (
                charge_normalization["sqm_atom_charge_print_quantum_e"] / 2 + 1e-10
            )
            assert "amber_outputs/antechamber_ligand_raw.mol2" in built_system.raw_artifacts
            assert "amber_outputs/ligand.mol2" in built_system.raw_artifacts
            assert built_system.system.net_charge == pytest.approx(0.0, abs=1e-5)
            if system_request.parameters["output_format"] == "gromacs":
                assert build_report["single_point_energy"]["gromacs_potential_kj_mol"] is not None
            disulfide_records = build_report["protein_preparation"]["disulfide_bonds"]
            assert len(disulfide_records) == 1
            assert set(disulfide_records[0]["residue_keys"]) == {"A:40:_", "A:114:_"}
            assert set(disulfide_records[0]["tleap_residue_indices"]) == {40, 114}
            assert disulfide_records[0]["sg_distance_A"] == pytest.approx(2.007, abs=0.02)
            assert (
                build_report["protein_identity_validation"][
                    "identity_match_except_documented_terminal_atoms"
                ]
                is True
            )
            assert build_report["ligand_identity_validation"]["max_coordinate_deviation_A"] <= 0.02
            assert build_report["conversion_validation"]["max_coordinate_deviation_A"] <= 0.002
            assert build_report["ligand_identity_validation"]["atom_order_and_graph_match"] is True
            assert (
                build_report["conversion_validation"]["atom_order_and_residue_identity_match"]
                is True
            )
            if OPENMM_PYTHON:
                native_inputs = built_system.system.engine_inputs["amber"]
                topology_ref = native_inputs["amber_outputs/system.prmtop"]
                coordinates_ref = native_inputs["amber_outputs/system.inpcrd"]
                assert topology_ref.sha256 is not None
                assert coordinates_ref.sha256 is not None
                stage_dir = tmp_path / "pose_openmm_minimization"
                stage_dir.mkdir()
                staged_topology = "amber_outputs/system.prmtop"
                staged_coordinates = "amber_outputs/system.inpcrd"
                for relative, ref in (
                    (staged_topology, topology_ref),
                    (staged_coordinates, coordinates_ref),
                ):
                    destination = stage_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(store.path_for(ref.sha256).read_bytes())
                minimization = MDStage(
                    kind=MDStageKind.MINIMIZATION,
                    integrator="minimize",
                    n_steps=10,
                    constraints="HBonds",
                    hmr=False,
                    nonbonded={
                        "method": "PME",
                        "cutoff_nm": 0.8,
                        "ewald_error_tolerance": 0.0005,
                    },
                )
                nvt = MDStage(
                    kind=MDStageKind.NVT,
                    integrator="langevin",
                    timestep_fs=2.0,
                    n_steps=10,
                    temperature_K=303.15,
                    thermostat="langevin",
                    constraints="HBonds",
                    hmr=False,
                    nonbonded={
                        "method": "PME",
                        "cutoff_nm": 0.8,
                        "ewald_error_tolerance": 0.0005,
                    },
                )
                minimized_build = built_system.model_copy(
                    update={"protocol": MDProtocol(stages=(minimization, nvt))}
                )
                stage_input = MDStageInput(
                    id=new_ulid(),
                    system_id=built_system.system.id,
                    compound_id=built_system.system.compound_id,
                    form_id=built_system.system.form_id,
                    stage_index=0,
                    artifacts={"topology": topology_ref, "coordinates": coordinates_ref},
                )
                context = AdapterContext(
                    inputs={"system_build": minimized_build, "stage_input": stage_input},
                    parameters={
                        "openmm": {
                            "stage_index": 0,
                            "python_executable": OPENMM_PYTHON,
                            "worker_script": str(ROOT / "src/caddsuite_worker/openmm_md_worker.py"),
                            "topology_path": staged_topology,
                            "coordinates_path": staged_coordinates,
                            "output_prefix": "pose_minimized",
                            "random_seed": 42,
                            "friction_per_ps": 1.0,
                            "report_interval_steps": 5,
                            "cpu_threads": 1,
                            "platform_name": "CPU",
                        }
                    },
                    working_directory=stage_dir,
                )
                openmm_adapter = OpenMMMDAdapter()
                assert openmm_adapter.validate_stage(context) == ()
                plan = openmm_adapter.plan_stage(context)
                completed = subprocess.run(
                    plan.commands[0].argv,
                    cwd=stage_dir,
                    env={**os.environ, **plan.commands[0].environment},
                    capture_output=True,
                    check=False,
                    shell=False,
                    timeout=300,
                )
                output = completed.stdout + completed.stderr
                assert completed.returncode == 0, output.decode(errors="replace")[-4000:]
                minimization_report = json.loads(
                    (stage_dir / "pose_minimized.result.json").read_text(encoding="utf-8")
                )
                assert minimization_report["software"]["name"] == "OpenMM"
                assert minimization_report["parameters"]["stage_kind"] == "minimization"
                assert minimization_report["maximum_iterations"] == 10
                assert minimization_report["atom_count"] == built_system.system.n_atoms
                assert minimization_report["potential_energy_kcal_mol"] <= (
                    minimization_report["initial_potential_energy_kcal_mol"] + 1e-5
                )
                minimized_pdb = stage_dir / "pose_minimized.pdb"
                assert minimized_pdb.is_file()
                minimized_coordinates_ref = ArtifactRef(
                    artifact_id=new_ulid(),
                    role="md_pdb",
                    sha256=hashlib.sha256(minimized_pdb.read_bytes()).hexdigest(),
                )
                nvt_input = MDStageInput(
                    id=new_ulid(),
                    system_id=built_system.system.id,
                    compound_id=built_system.system.compound_id,
                    form_id=built_system.system.form_id,
                    stage_index=1,
                    artifacts={
                        "topology": topology_ref,
                        "coordinates": minimized_coordinates_ref,
                    },
                )
                nvt_context = AdapterContext(
                    inputs={"system_build": minimized_build, "stage_input": nvt_input},
                    parameters={
                        "openmm": {
                            "stage_index": 1,
                            "python_executable": OPENMM_PYTHON,
                            "worker_script": str(ROOT / "src/caddsuite_worker/openmm_md_worker.py"),
                            "topology_path": staged_topology,
                            "coordinates_path": "pose_minimized.pdb",
                            "output_prefix": "pose_nvt",
                            "random_seed": 42,
                            "friction_per_ps": 1.0,
                            "report_interval_steps": 5,
                            "cpu_threads": 1,
                            "platform_name": "CPU",
                        }
                    },
                    working_directory=stage_dir,
                )
                assert openmm_adapter.validate_stage(nvt_context) == ()
                nvt_plan = openmm_adapter.plan_stage(nvt_context)
                completed = subprocess.run(
                    nvt_plan.commands[0].argv,
                    cwd=stage_dir,
                    env={**os.environ, **nvt_plan.commands[0].environment},
                    capture_output=True,
                    check=False,
                    shell=False,
                    timeout=300,
                )
                output = completed.stdout + completed.stderr
                assert completed.returncode == 0, output.decode(errors="replace")[-4000:]
                nvt_report = json.loads(
                    (stage_dir / "pose_nvt.result.json").read_text(encoding="utf-8")
                )
                assert nvt_report["parameters"]["stage_kind"] == "nvt"
                assert nvt_report["steps_completed"] == 10
                assert nvt_report["time_ps"] == pytest.approx(0.02)
                assert nvt_report["atom_count"] == built_system.system.n_atoms
                if MDA_PYTHON:
                    production = MDStage(
                        kind=MDStageKind.PRODUCTION,
                        integrator="langevin",
                        timestep_fs=2.0,
                        n_steps=50,
                        temperature_K=303.15,
                        thermostat="langevin",
                        constraints="HBonds",
                        hmr=False,
                        nonbonded={
                            "method": "PME",
                            "cutoff_nm": 0.8,
                            "ewald_error_tolerance": 0.0005,
                        },
                    )
                    production_build = built_system.model_copy(
                        update={"protocol": MDProtocol(stages=(minimization, nvt, production))}
                    )
                    nvt_pdb = stage_dir / "pose_nvt.pdb"
                    nvt_blob = store.put_file(nvt_pdb)
                    production_input = MDStageInput(
                        id=new_ulid(),
                        system_id=built_system.system.id,
                        compound_id=built_system.system.compound_id,
                        form_id=built_system.system.form_id,
                        stage_index=2,
                        artifacts={
                            "topology": topology_ref,
                            "coordinates": ArtifactRef(
                                artifact_id=new_ulid(), role="md_pdb", sha256=nvt_blob.sha256
                            ),
                        },
                    )
                    production_stage = StageDefinition.model_validate(
                        {
                            "id": "pose_openmm_production",
                            "kind": "molecular_dynamics",
                            "engine": "openmm",
                            "params": {
                                "engine_parameters": {
                                    "memory_MiB": 4096,
                                    "timeout_seconds": 600,
                                    "openmm": {
                                        "stage_index": 2,
                                        "python_executable": OPENMM_PYTHON,
                                        "worker_script": str(
                                            ROOT / "src/caddsuite_worker/openmm_md_worker.py"
                                        ),
                                        "topology_path": staged_topology,
                                        "coordinates_path": "pose_nvt.pdb",
                                        "output_prefix": "pose_production",
                                        "random_seed": 43,
                                        "friction_per_ps": 1.0,
                                        "report_interval_steps": 5,
                                        "cpu_threads": 2,
                                        "platform_name": "CPU",
                                    },
                                }
                            },
                        }
                    )
                    production_handler = MDStagePlugin._build(
                        "openmm", production_stage, runtime.services
                    )
                    production_result = cast(
                        MDStageResult,
                        production_handler.execute(
                            cast(
                                TaskInvocation,
                                SimpleNamespace(
                                    inputs={
                                        "system_build": (production_build,),
                                        "stage_input": (production_input,),
                                    }
                                ),
                            )
                        ),
                    )
                    assert production_result.stage_kind is MDStageKind.PRODUCTION
                    assert production_result.stage_index == 2
                    assert production_result.compound_id == compound.id
                    assert production_result.form_id == form.id
                    assert any(ref.role == "md_dcd" for ref in production_result.artifacts.values())

                    dcd_key = next(
                        key
                        for key, ref in production_result.artifacts.items()
                        if ref.role == "md_dcd"
                    )
                    pdb_key = next(
                        key
                        for key, ref in production_result.artifacts.items()
                        if ref.role == "md_pdb"
                    )
                    trajectory_plan = MDOutputTrajectoryPlan(
                        simulation_id=new_ulid(),
                        topology_output_key=pdb_key,
                        trajectory_output_key=dcd_key,
                        topology_format="PDB",
                        trajectory_format="DCD",
                        topology_has_connectivity=False,
                        output_start_time_ps=0.01,
                        n_frames=10,
                        frame_interval_ps=0.01,
                        transforms=(TrajectoryTransform.VALIDATE_ONLY,),
                    )
                    processing_request = MDOutputTrajectoryBindingHandler(runtime.services).execute(
                        cast(
                            TaskInvocation,
                            SimpleNamespace(
                                inputs={
                                    "system_build": (production_build,),
                                    "md_result": (production_result,),
                                    "plan": (trajectory_plan,),
                                }
                            ),
                        )
                    )
                    processor_stage = StageDefinition.model_validate(
                        {
                            "id": "pose_dcd_validate",
                            "kind": "trajectory.process",
                            "engine": "mdanalysis",
                            "params": {
                                "engine_parameters": {
                                    "python_executable": MDA_PYTHON,
                                    "worker_script": str(
                                        ROOT
                                        / "src/caddsuite_worker/mdanalysis_trajectory_worker.py"
                                    ),
                                }
                            },
                        }
                    )
                    processed = cast(
                        TrajectoryProcessingResult,
                        MDAnalysisTrajectoryStagePlugin._build(
                            processor_stage, runtime.services
                        ).execute(
                            cast(
                                TaskInvocation,
                                SimpleNamespace(inputs={"request": (processing_request,)}),
                            )
                        ),
                    )
                    assert processed.time_range_ps == pytest.approx((0.01, 0.10), abs=1e-5)

                    source_selections = built_system.system.selections
                    assert "protein" in source_selections
                    assert "ligand" in source_selections
                    # The builder's selections are GROMACS index artifacts. For the
                    # generated PDB/DCD pair, use equivalent named selections and let
                    # MDAnalysis verify their atom counts against the topology.
                    selections = {
                        "protein": AtomSelection(
                            description="protein",
                            n_atoms=source_selections["protein"].n_atoms,
                            verified=True,
                        ),
                        "ligand": AtomSelection(
                            description="resname LIG",
                            n_atoms=source_selections["ligand"].n_atoms,
                            verified=True,
                        ),
                    }
                    analysis_plan = TrajectoryAnalysisPlan(
                        id=new_ulid(),
                        simulation_id=trajectory_plan.simulation_id,
                        trajectory_id=new_ulid(),
                        compound_id=compound.id,
                        form_id=form.id,
                        selections={
                            "protein": selections["protein"],
                            "ligand": selections["ligand"],
                        },
                        metrics=(TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,),
                        start_time_ns=0.00001,
                        end_time_ns=0.00010,
                    )
                    analysis_stage = StageDefinition.model_validate(
                        {
                            "id": "pose_dcd_metrics",
                            "kind": "trajectory.analyze_processed",
                            "engine": "mdanalysis",
                            "params": {
                                "engine_parameters": {
                                    "python_executable": MDA_PYTHON,
                                    "worker_script": str(
                                        ROOT / "src/caddsuite_worker/mdanalysis_metrics_worker.py"
                                    ),
                                }
                            },
                        }
                    )
                    analysis_result = cast(
                        TrajectoryAnalysisResult,
                        TrajectoryAnalysisStagePlugin._build(
                            analysis_stage, runtime.services
                        ).execute(
                            cast(
                                TaskInvocation,
                                SimpleNamespace(
                                    inputs={
                                        "analysis_plan": (analysis_plan,),
                                        "preprocessing": (processed,),
                                    }
                                ),
                            )
                        ),
                    )
                    assert analysis_result.simulation_id == trajectory_plan.simulation_id
                    assert analysis_result.compound_id == compound.id
                    assert analysis_result.form_id == form.id

                    report_stage = StageDefinition.model_validate(
                        {
                            "id": "pose_report",
                            "kind": "report",
                            "params": {"formats": ["json", "html"]},
                        }
                    )
                    report_bundle = cast(
                        ReportBundle,
                        ReportStagePlugin._build(report_stage, runtime.services).execute(
                            cast(
                                TaskInvocation,
                                SimpleNamespace(
                                    run_id=str(run.id),
                                    inputs={
                                        "compounds": (compound,),
                                        "compound_forms": (form,),
                                        "docking_results": (result,),
                                        "md_results": (production_result,),
                                        "trajectory_results": (analysis_result,),
                                    },
                                ),
                            )
                        ),
                    )
                    report_ref = next(
                        artifact.artifact
                        for artifact in report_bundle.artifacts
                        if artifact.format == "json"
                    )
                    report_json = json.loads(
                        store.path_for(report_ref.sha256 or "").read_text(encoding="utf-8")
                    )
                    trajectory_report_sections = {
                        section["name"]: section for section in report_json["sections"]
                    }
                    trajectory_section = trajectory_report_sections["trajectory_analyses"]
                    assert trajectory_section["status"] == "available"
                    assert trajectory_section["data"][0]["compound_id"] == str(compound.id)
                    assert trajectory_section["data"][0]["form_id"] == str(form.id)
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
