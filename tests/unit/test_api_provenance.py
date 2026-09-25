from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caddsuite.api.provenance import create_app
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.execution import AttemptArtifact, AttemptStatus
from caddsuite.domain.enums import TaskState
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.storage.paths import artifacts_root, database_path
from caddsuite.storage.task_state import TaskStateStore
from tests.unit.test_attempt_store import _running_attempt


def _seed_project_run(root: Path) -> tuple[str, str, str]:
    migrate.upgrade(database_path(root))
    engine = create_db_engine(database_path(root))
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="api-provenance", name="API provenance")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-API-001",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="succeeded",
        )
        session.add(run)
        session.flush()
        project_id, run_id = project.id, run.id
    task_store = TaskStateStore(sessions)
    task = task_store.create(run_id=run_id, stage_id="standardize")
    task = task_store.transition(
        task.id, expected=task.state, target=TaskState.READY, expected_version=task.version
    )
    task = task_store.transition(
        task.id, expected=task.state, target=TaskState.RUNNING, expected_version=task.version
    )
    artifacts = ArtifactStore(artifacts_root(root))
    input_blob = artifacts.put_bytes(b"normalized input")
    output_blob = artifacts.put_bytes(b"normalized output")
    with sessions.begin() as session:
        input_row = register_blob(session, input_blob, kind="input", media_type="application/json")
        output_row = register_blob(
            session, output_blob, kind="output", media_type="application/json"
        )
    store = TaskAttemptStore(sessions)
    attempt = store.begin(
        _running_attempt(
            task.id,
            ArtifactRef(artifact_id=input_row.id, role="input", sha256=input_row.sha256),
        )
    )
    store.finish(
        str(attempt.id),
        status=AttemptStatus.SUCCEEDED,
        ended_at=datetime.now(UTC),
        steps=(),
        generated_artifacts=(
            AttemptArtifact(
                artifact=ArtifactRef(
                    artifact_id=output_row.id, role="result", sha256=output_row.sha256
                ),
                direction="generated",
                role="normalized_result",
            ),
        ),
    )
    engine.dispose()
    return project_id, run_id, str(attempt.id)


def test_provenance_api_authenticates_and_returns_project_and_run_graphs(tmp_path: Path) -> None:
    project_id, run_id, attempt_id = _seed_project_run(tmp_path)
    app = create_app(
        data_root=tmp_path,
        token="test-secret",  # noqa: S106
        allowed_origins=("http://127.0.0.1:5173",),
    )
    with TestClient(app) as client:
        assert client.get(f"/v1/provenance/runs/{run_id}").status_code == 401
        blocked = client.get(
            f"/v1/provenance/runs/{run_id}",
            headers={"Authorization": "Bearer test-secret", "Origin": "https://unexpected.test"},
        )
        assert blocked.status_code == 403
        headers = {
            "Authorization": "Bearer test-secret",
            "Origin": "http://127.0.0.1:5173",
        }
        run = client.get(f"/v1/provenance/runs/{run_id}", headers=headers)
        assert run.status_code == 200
        assert run.json()["run_id"] == run_id
        assert [item["id"] for item in run.json()["attempts"]] == [attempt_id]
        assert {(item["direction"], item["role"]) for item in run.json()["edges"]} == {
            ("used", "geometry"),
            ("generated", "normalized_result"),
        }
        attempt = client.get(f"/v1/provenance/attempts/{attempt_id}", headers=headers)
        assert attempt.status_code == 200
        assert attempt.json()["root_attempt_id"] == attempt_id
        project = client.get(f"/v1/provenance/projects/{project_id}", headers=headers)
        assert project.status_code == 200
        assert project.json()["project_id"] == project_id
        assert project.json()["run_ids"] == [run_id]
        drift = client.get(f"/v1/provenance/projects/{project_id}/version-drift", headers=headers)
        assert drift.status_code == 200
        assert drift.json()["warnings"] == []
        missing = client.get("/v1/provenance/attempts/no-such-attempt", headers=headers)
        assert missing.status_code == 404


def _docking_workflow_payload() -> dict[str, object]:
    return {
        "schema": "caddsuite.workflow/1",
        "name": "Docking plan",
        "inputs": {
            "compound": {"contract": "compound/1.0"},
            "form": {"contract": "compound_form/1.0"},
            "conformer": {"contract": "conformer/1.1"},
            "receptor": {"contract": "prepared_receptor/1.0"},
            "target": {"contract": "structure/1.0"},
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
                    "target_structure": "$target",
                    "site": "$site",
                },
                "output_contract": "docking_result/1.0",
                "params": {},
            }
        ],
        "outputs": {"result": "dock"},
    }


def test_workflow_plan_status_and_run_submission_validation(tmp_path: Path) -> None:
    project_id, run_id, _attempt_id = _seed_project_run(tmp_path)
    app = create_app(data_root=tmp_path, token="test-secret")  # noqa: S106
    headers = {"Authorization": "Bearer test-secret"}
    with TestClient(app) as client:
        status_response = client.get(
            f"/v1/projects/{project_id}/runs/{run_id}/status", headers=headers
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "succeeded"
        assert [row["stage_id"] for row in status_response.json()["tasks"]] == ["standardize"]

        capabilities = client.get("/v1/workflows/capabilities", headers=headers)
        assert capabilities.status_code == 200
        assert any(
            item["kind"] == "docking" and item["engine"] == "vina"
            for item in capabilities.json()["capabilities"]
        )

        workflow = _docking_workflow_payload()
        plan = client.post("/v1/workflows/plan", headers=headers, json=workflow)
        assert plan.status_code == 200, plan.text
        assert plan.json()["task_order"] == ["dock"]

        rejected = client.post(
            f"/v1/projects/{project_id}/runs/01ARZ3NDEKTSV4RRFFQ69G5FAV/execute",
            headers=headers,
            json={"workflow": workflow, "inputs": {}},
        )
        assert rejected.status_code == 422
        assert "inputs must exactly match" in rejected.json()["detail"]


def test_provenance_api_requires_nonempty_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="token must be configured"):
        create_app(data_root=tmp_path, token="")
