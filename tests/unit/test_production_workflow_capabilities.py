"""The published ADMET/docking/report template compiles against installed production plugins."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import yaml

from caddsuite.application.binding_site_stage_plugin import BlindProteinSiteStageHandler
from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.registry import CompoundFormSet, Conformer
from caddsuite.contracts.reporting import ReportBundle
from caddsuite.contracts.structure import (
    BindingSite,
    BindingSiteMethod,
    PreparedReceptor,
    Structure,
    StructureSource,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind, TaskState
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.decisions import DecisionStore
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.storage.task_state import TaskStateStore
from caddsuite.validation.decisions import Decision
from caddsuite.workflow.definition import StageDefinition, WorkflowDefinition
from caddsuite.workflow.scheduler import StageHandler, TaskInvocation


def test_pdbfixer_stage_is_discovered_without_importing_engine_runtime() -> None:
    registry = StageHandlerRegistry.discover()
    capability = registry.snapshot().capabilities.resolve("structure.prepare_protein", "pdbfixer")
    assert capability is not None
    assert capability.outputs == ("prepared_receptor/1.3",)


def test_admet_docking_report_template_compiles_with_discovered_plugins() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / "workflows" / "admet_docking_report.yaml"
    workflow = WorkflowDefinition.model_validate(yaml.safe_load(workflow_path.read_text()))
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    assert compiled.task_order == (
        "admet",
        "protonate",
        "configured_filter",
        "embed",
        "prepare_protein",
        "binding_site",
        "dock",
        "report",
    )
    tasks = {task.stage_id: task for task in compiled.tasks}
    assert tasks["prepare_protein"].output_contract == "prepared_receptor/1.3"
    assert tasks["binding_site"].output_contract == "binding_site/1.0"
    assert tasks["dock"].output_contract == "docking_result/1.0"
    assert tasks["dock"].params["docking_parameters"]["energy_range_kcal_mol"] == 3.0
    assert tasks["dock"].params["docking_parameters"]["cpu_cores"] == 2
    assert tasks["dock"].dependencies == (
        "binding_site",
        "configured_filter",
        "embed",
        "prepare_protein",
    )
    assert tasks["report"].output_contract == "report_bundle/1.0"


def test_discovered_runtime_executes_admet_to_report_subworkflow(tmp_path: Path) -> None:
    registry = StageHandlerRegistry.discover()
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "ADMET to report runtime regression",
            "inputs": {"compounds": {"contract": "compound/1.0"}},
            "stages": [
                {
                    "id": "admet",
                    "kind": "property_prediction",
                    "engine": "rdkit_rules",
                    "for_each": "compound",
                    "input_contracts": {"compound": "compound/1.0"},
                    "input_bindings": {"compound": "$compounds"},
                    "output_contract": "property_prediction_set/1.0",
                    "params": {"endpoints": ["qed", "physicochemistry"]},
                },
                {
                    "id": "protonate",
                    "kind": "chemistry.protonate",
                    "engine": "dimorphite_dl",
                    "for_each": "compound",
                    "input_contracts": {"compound": "compound/1.0"},
                    "input_bindings": {"compound": "$compounds"},
                    "output_contract": "compound_form/1.0",
                    "params": {"target_ph": 7.4, "ambiguous_microstates": "require_decision"},
                },
                {
                    "id": "embed",
                    "kind": "chemistry.embed",
                    "engine": "rdkit_etkdg",
                    "for_each": "compound",
                    "needs": ["protonate"],
                    "input_contracts": {"form": "compound_form/1.0"},
                    "input_bindings": {"form": "protonate"},
                    "output_contract": "conformer/1.1",
                    "params": {"policy": {"seed": 42, "optimizer": "MMFF94"}},
                },
                {
                    "id": "report",
                    "kind": "report",
                    "needs": ["admet", "embed"],
                    "input_contracts": {
                        "compounds": "compound/1.0",
                        "property_results": "property_prediction_set/1.0",
                    },
                    "input_bindings": {
                        "compounds": "$compounds",
                        "property_results": "admet",
                    },
                    "output_contract": "report_bundle/1.0",
                    "params": {"formats": ["json", "html"]},
                },
            ],
            "outputs": {"report": "report", "conformer": "embed"},
        }
    )
    compiled = registry.compile(workflow)

    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda services: registry.build_handlers(workflow, services),
    ) as runtime:
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="admet-report-runtime", name="ADMET report runtime")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-20260928-001",
                workflow_hash="c" * 64,
                config_hash="d" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            project_id, run_id = project.id, run.id

        smiles = "CCO"
        compound = make_compound(
            standardize_smiles(smiles),
            compound_id=new_ulid(),
            project_id=project_id,
            accession="CMP0001",
            name="ethanol",
            original_text=smiles,
            source="manual",
        )
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={"compounds": (compound,)},
        )
        assert not outcome.failures
        conformer = outcome.outputs["conformer"][0].value
        assert isinstance(conformer, Conformer)
        assert conformer.schema_id() == "conformer/1.1"
        assert conformer.seed == 42
        assert conformer.structure.sha256 is not None
        assert runtime.services.artifacts.verify(conformer.structure.sha256)
        bundle = outcome.outputs["report"][0].value
        assert isinstance(bundle, ReportBundle)
        assert {item.format for item in bundle.artifacts} == {"json", "html"}
        json_artifact = next(item.artifact for item in bundle.artifacts if item.format == "json")
        assert json_artifact.sha256 is not None
        report_bytes = runtime.services.artifacts.path_for(json_artifact.sha256).read_bytes()
        assert b"qed" in report_bytes
        assert b"experimental validation" in report_bytes


def test_blind_binding_site_stage_registers_method_and_receptor_lineage(tmp_path: Path) -> None:
    data = (
        Path(__file__).resolve().parents[1] / "data" / "golden" / "structure_g1" / "5NIU.cif"
    ).read_bytes()
    target_id = new_ulid()
    structure_id = new_ulid()
    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "binding-site",
        handlers=lambda _services: {"unused": cast(StageHandler, object())},
    ) as runtime:
        blob = runtime.services.artifacts.put_bytes(data)
        with runtime.sessions.begin() as session:
            source_row = register_blob(
                session,
                blob,
                kind="raw_structure",
                media_type="chemical/x-mmcif",
                original_name="5NIU.cif",
            )
        source_ref = ArtifactRef(
            artifact_id=source_row.id,
            role="raw_structure_mmcif",
            sha256=blob.sha256,
        )
        structure = Structure(
            id=structure_id,
            target_id=target_id,
            source=StructureSource.RCSB,
            source_id="5NIU",
            raw=source_ref,
        )
        prepared_ref = source_ref.model_copy(update={"role": "prepared_structure"})
        receptor = PreparedReceptor(
            id=new_ulid(),
            structure_id=structure_id,
            protocol=SoftwareRef(
                name="PDBFixer",
                version="test-fixture",
                kind=SoftwareKind.LIBRARY,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
            ph=7.4,
            protonation_method="test-fixture",
            selected_chain_ids=("A",),
            artifacts={"prepared_structure": prepared_ref},
        )
        stage = StageDefinition.model_validate(
            {
                "id": "site",
                "kind": "structure.binding_site",
                "engine": "blind_protein_box",
                "params": {"selected_chain_ids": ["A"]},
            }
        )
        handler = BlindProteinSiteStageHandler(stage, runtime.services)
        site = handler.execute(
            cast(
                TaskInvocation,
                SimpleNamespace(inputs={"structure": (structure,), "receptor": (receptor,)}),
            )
        )
        assert isinstance(site, BindingSite)
        assert site.method is BindingSiteMethod.BLIND_WHOLE_PROTEIN
        assert site.source_receptor == prepared_ref
        assert site.volume_A3 > 0


def test_real_multi_form_enumeration_fans_out_to_independent_conformers(tmp_path: Path) -> None:
    workflow_path = Path(__file__).resolve().parents[2] / "workflows" / "multi_form_embedding.yaml"
    workflow = WorkflowDefinition.from_yaml(workflow_path)
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)

    with LocalWorkflowRuntime.open(
        data_root=tmp_path / "multi-form-runtime",
        handlers=lambda services: registry.build_handlers(workflow, services),
    ) as runtime:
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="multi-form-runtime", name="Multi-form runtime")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-MULTIFORM-001",
                workflow_hash="e" * 64,
                config_hash="f" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            project_id, run_id = project.id, run.id

        compound = make_compound(
            standardize_smiles("NCC(=O)O"),
            compound_id=new_ulid(),
            project_id=project_id,
            accession="CMP0001",
            name="glycine",
            original_text="NCC(=O)O",
            source="manual",
        )
        first = runtime.run(
            compiled,
            run_id=run_id,
            inputs={"compounds": (compound,)},
        )
        pause = next(task for task in first.tasks if task.state is TaskState.AWAITING_DECISION)
        request = pause.decision_request
        assert request is not None
        run_all = next(option for option in request.options if option.key == "run_all")
        decision = Decision(
            request=request,
            chosen_key=run_all.key,
            decided_by="automated integration fixture",
            decided_at=datetime.now(UTC),
        )
        DecisionStore(runtime.sessions).submit(
            pause.task_id,
            decision,
            expected_version=TaskStateStore(runtime.sessions).get(pause.task_id).version,
        )

        resumed = runtime.run(
            compiled,
            run_id=run_id,
            inputs={"compounds": (compound,)},
        )

        assert not resumed.failures
        enumeration = next(task for task in resumed.tasks if task.stage_id == "enumerate_forms")
        assert isinstance(enumeration.result, CompoundFormSet)
        forms = enumeration.result.items
        assert len(forms) > 1
        embed_tasks = [task for task in resumed.tasks if task.stage_id == "embed_each_form"]
        assert {task.subject_id for task in embed_tasks} == {str(form.id) for form in forms}
        assert {task.state for task in embed_tasks} == {TaskState.SUCCEEDED}
        conformers = [item.value for item in resumed.outputs["conformers"]]
        assert {item.form_id for item in conformers} == {form.id for form in forms}
        assert all(
            item.structure.sha256 is not None
            and runtime.services.artifacts.verify(item.structure.sha256)
            for item in conformers
        )
