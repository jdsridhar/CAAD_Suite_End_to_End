"""Application-to-worker QM integration and provenance test (opt-in engine)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from caddsuite.application.handlers import StageHandlerRegistry
from caddsuite.application.runtime import LocalRuntimeServices, LocalWorkflowRuntime
from caddsuite.contracts.execution import TaskAttempt
from caddsuite.storage.artifacts import register_blob
from caddsuite.storage.models import ProjectRow, TaskAttemptRow, WorkflowRunRow
from caddsuite.workflow.definition import WorkflowDefinition

PYSCF_PYTHON = os.environ.get("CADDSUITE_PYSCF_PYTHON")
PSI4_PYTHON = os.environ.get("CADDSUITE_PSI4_PYTHON")
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.engine("PySCF")
@pytest.mark.slow
@pytest.mark.skipif(
    not PYSCF_PYTHON, reason="set CADDSUITE_PYSCF_PYTHON for application-level QM integration"
)
def test_pyscf_application_run_records_normalized_result_and_provenance(tmp_path: Path) -> None:
    from tests.integration.test_pyscf_adapter import _case

    assert PYSCF_PYTHON is not None
    calculation, raw_inputs, _staged, params, sdf = _case(tmp_path, PYSCF_PYTHON)
    form = raw_inputs["form"]
    conformer = raw_inputs["conformer"]
    registry = StageHandlerRegistry.discover()
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "QM application integration",
            "inputs": {
                "calculation": {"contract": "qm_calculation/1.1"},
                "form": {"contract": "compound_form/1.0"},
                "conformer": {"contract": "conformer/1.1"},
            },
            "stages": [
                {
                    "id": "qm",
                    "kind": "quantum_chemistry",
                    "engine": "caddsuite.qm.pyscf",
                    "input_contracts": {
                        "calculation": "qm_calculation/1.1",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                    },
                    "input_bindings": {
                        "calculation": "$calculation",
                        "form": "$form",
                        "conformer": "$conformer",
                    },
                    "output_contract": "qm_result/2.0",
                    "params": {"engine_parameters": params},
                }
            ],
            "outputs": {"result": "qm"},
        }
    )
    compiled = registry.compile(workflow)

    def build(services: LocalRuntimeServices) -> Mapping[str, object]:
        return registry.build_handlers(workflow, services)

    with LocalWorkflowRuntime.open(data_root=tmp_path / "platform", handlers=build) as runtime:
        blob = runtime.services.artifacts.put_file(sdf)
        with runtime.sessions.begin() as session:
            artifact_row = register_blob(
                session,
                blob,
                kind="qm_input",
                media_type="chemical/x-mdl-sdfile",
                original_name=sdf.name,
            )
        conformer = conformer.model_copy(
            update={
                "structure": conformer.structure.model_copy(
                    update={"artifact_id": artifact_row.id, "sha256": blob.sha256}
                )
            }
        )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="qm-app", name="QM app integration")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-QM-APP-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={"calculation": calculation, "form": form, "conformer": conformer},
        )
        assert not outcome.failures
        result = outcome.outputs["result"][0].value
        assert result.schema_version == "qm_result/2.0"
        assert result.total_energy_Eh < 0.0
        with runtime.sessions() as session:
            attempt_row = session.scalar(select(TaskAttemptRow))
        assert attempt_row is not None
        attempt = TaskAttempt.model_validate(attempt_row.payload)
        assert attempt.status.value == "succeeded"
        assert attempt.steps
        assert attempt.resources is not None
        assert attempt.resources.cpu_cores == 1
        assert attempt.resources.memory_MiB == 2000
        assert attempt.environment is not None
        assert attempt.environment.name == "caddsuite-pyscf"
        assert attempt.environment.lock is not None
        assert any(item.role == "final_geometry" for item in attempt.artifacts)
        assert any(item.direction == "used" for item in attempt.artifacts)


@pytest.mark.engine("Psi4")
@pytest.mark.slow
@pytest.mark.skipif(
    not PSI4_PYTHON, reason="set CADDSUITE_PSI4_PYTHON for application-level QM integration"
)
def test_psi4_application_run_records_normalized_result_and_provenance(tmp_path: Path) -> None:
    from tests.unit.test_psi4_adapter import _case as psi4_case

    assert PSI4_PYTHON is not None
    calculation, raw_inputs, _staged, params, sdf = psi4_case(tmp_path)
    params["python_executable"] = PSI4_PYTHON
    form = raw_inputs["form"]
    conformer = raw_inputs["conformer"]
    registry = StageHandlerRegistry.discover()
    workflow = WorkflowDefinition.model_validate(
        {
            "schema": "caddsuite.workflow/1",
            "name": "QM application integration",
            "inputs": {
                "calculation": {"contract": "qm_calculation/1.1"},
                "form": {"contract": "compound_form/1.0"},
                "conformer": {"contract": "conformer/1.1"},
            },
            "stages": [
                {
                    "id": "qm",
                    "kind": "quantum_chemistry",
                    "engine": "caddsuite.qm.psi4",
                    "input_contracts": {
                        "calculation": "qm_calculation/1.1",
                        "form": "compound_form/1.0",
                        "conformer": "conformer/1.1",
                    },
                    "input_bindings": {
                        "calculation": "$calculation",
                        "form": "$form",
                        "conformer": "$conformer",
                    },
                    "output_contract": "qm_result/2.0",
                    "params": {"engine_parameters": params},
                }
            ],
            "outputs": {"result": "qm"},
        }
    )
    compiled = registry.compile(workflow)

    def build(services: LocalRuntimeServices) -> Mapping[str, object]:
        return registry.build_handlers(workflow, services)

    with LocalWorkflowRuntime.open(data_root=tmp_path / "platform", handlers=build) as runtime:
        blob = runtime.services.artifacts.put_file(sdf)
        with runtime.sessions.begin() as session:
            artifact_row = register_blob(
                session,
                blob,
                kind="qm_input",
                media_type="chemical/x-mdl-sdfile",
                original_name=sdf.name,
            )
        conformer = conformer.model_copy(
            update={
                "structure": conformer.structure.model_copy(
                    update={"artifact_id": artifact_row.id, "sha256": blob.sha256}
                )
            }
        )
        with runtime.sessions.begin() as session:
            project = ProjectRow(slug="qm-app", name="QM app integration")
            session.add(project)
            session.flush()
            run = WorkflowRunRow(
                project_id=project.id,
                accession="RUN-QM-APP-001",
                workflow_hash="a" * 64,
                config_hash="b" * 64,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            run_id = run.id
        outcome = runtime.run(
            compiled,
            run_id=run_id,
            inputs={"calculation": calculation, "form": form, "conformer": conformer},
        )
        assert not outcome.failures
        result = outcome.outputs["result"][0].value
        assert result.schema_version == "qm_result/2.0"
        assert result.total_energy_Eh < 0.0
        with runtime.sessions() as session:
            attempt_row = session.scalar(select(TaskAttemptRow))
        assert attempt_row is not None
        attempt = TaskAttempt.model_validate(attempt_row.payload)
        assert attempt.status.value == "succeeded"
        assert attempt.steps
        assert attempt.resources is not None
        assert attempt.resources.cpu_cores == 1
        assert attempt.resources.memory_MiB == 2048
        assert attempt.environment is not None
        assert attempt.environment.name == "psi4"
        assert attempt.environment.lock is not None
        assert any(item.role == "final_geometry" for item in attempt.artifacts)
        assert any(item.direction == "used" for item in attempt.artifacts)
