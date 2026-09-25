"""Opt-in end-to-end CLI execution through the real PySCF worker."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from caddsuite.cli.main import app
from caddsuite.contracts.execution import TaskAttempt
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import TaskAttemptRow, WorkflowRunRow

PYSCF_PYTHON = os.environ.get("CADDSUITE_PYSCF_PYTHON")
runner = CliRunner()


@pytest.mark.engine("PySCF")
@pytest.mark.slow
@pytest.mark.skipif(
    not PYSCF_PYTHON, reason="set CADDSUITE_PYSCF_PYTHON for CLI engine integration"
)
def test_cli_run_executes_real_qm_workflow_and_persists_attempt(tmp_path: Path) -> None:
    from tests.integration.test_pyscf_adapter import _case

    assert PYSCF_PYTHON is not None
    calculation, raw_inputs, _, params, sdf = _case(tmp_path, PYSCF_PYTHON)
    form = raw_inputs["form"]
    conformer = raw_inputs["conformer"]
    conformer_payload = conformer.model_dump(mode="json")
    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "CLI QM integration",
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
    workflow_path = tmp_path / "workflow.yaml"
    import yaml

    workflow_path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    manifest_path = tmp_path / "inputs.json"
    manifest_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "calculation": calculation.model_dump(mode="json"),
                    "form": form.model_dump(mode="json"),
                    "conformer": conformer_payload,
                },
                "artifacts": {str(conformer.structure.artifact_id): str(sdf)},
            }
        ),
        encoding="utf-8",
    )
    data_root = tmp_path / "platform"
    created = runner.invoke(
        app,
        [
            "project",
            "create",
            "cli-qm",
            "--name",
            "CLI QM integration",
            "--data-root",
            str(data_root),
        ],
    )
    assert created.exit_code == 0, created.output
    project_id = json.loads(created.output)["id"]
    run = runner.invoke(
        app,
        [
            "run",
            str(workflow_path),
            "--project",
            project_id,
            "--inputs",
            str(manifest_path),
            "--data-root",
            str(data_root),
        ],
    )
    assert run.exit_code == 0, run.output
    report = json.loads(run.output)
    assert report["status"] == "succeeded"
    assert report["tasks"][0]["state"] == "succeeded"
    engine = create_db_engine(data_root / "caddsuite.db")
    sessions = make_session_factory(engine)
    try:
        with sessions() as session:
            run_row = session.get(WorkflowRunRow, report["run_id"])
            attempt = session.scalar(select(TaskAttemptRow))
        assert run_row is not None
        assert run_row.status == "succeeded"
        assert attempt is not None
        attempt_contract = TaskAttempt.model_validate(attempt.payload)
        assert attempt_contract.status.value == "succeeded"
        assert attempt_contract.environment is not None
        assert attempt_contract.resources is not None
        assert attempt_contract.steps
        assert any(edge.direction == "generated" for edge in attempt_contract.artifacts)
    finally:
        engine.dispose()
