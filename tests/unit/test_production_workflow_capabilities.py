"""The published ADMET/docking/report template compiles against installed production plugins."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.contracts.reporting import ReportBundle
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.workflow.definition import WorkflowDefinition


def test_admet_docking_report_template_compiles_with_discovered_plugins() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / "workflows" / "admet_docking_report.yaml"
    workflow = WorkflowDefinition.model_validate(yaml.safe_load(workflow_path.read_text()))
    registry = StageHandlerRegistry.discover()
    compiled = registry.compile(workflow)
    assert compiled.task_order == (
        "admet",
        "protonate",
        "configured_filter",
        "dock",
        "report",
    )
    assert compiled.tasks[3].output_contract == "docking_result/1.0"
    assert compiled.tasks[4].output_contract == "report_bundle/1.0"


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
                    "id": "report",
                    "kind": "report",
                    "needs": ["admet"],
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
            "outputs": {"report": "report"},
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
        bundle = outcome.outputs["report"][0].value
        assert isinstance(bundle, ReportBundle)
        assert {item.format for item in bundle.artifacts} == {"json", "html"}
        json_artifact = next(item.artifact for item in bundle.artifacts if item.format == "json")
        assert json_artifact.sha256 is not None
        report_bytes = runtime.services.artifacts.path_for(json_artifact.sha256).read_bytes()
        assert b"qed" in report_bytes
        assert b"experimental validation" in report_bytes
