from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caddsuite.api.provenance import create_app
from caddsuite.application.handlers import StageHandlerRegistration, StageHandlerRegistry
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.evidence import Candidate
from caddsuite.contracts.execution import AttemptArtifact, AttemptStatus
from caddsuite.domain.enums import TaskState
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import CommandSpec
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import (
    ArtifactRow,
    ProjectArtifactRow,
    ProjectRow,
    TaskAttemptRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import artifacts_root, database_path
from caddsuite.storage.task_state import TaskStateStore
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.scheduler import TaskInvocation
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


class _EchoCandidateHandler:
    adapter_id = "tests.echo_candidate"
    adapter_version = "1.0.0"
    engine_version = "test"

    def subject_key(self, _scope: str, value: object) -> str:
        return "candidate"

    def artifact_hashes(self, _inputs: object) -> dict[str, str]:
        return {}

    def gate_context(self, _inputs: object) -> tuple[dict[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> Candidate:
        value = invocation.inputs["candidate"][0]
        assert isinstance(value, Candidate)
        return value


class _EchoCandidatePlugin:
    plugin_id = "tests.echo_candidate"
    version = "1.0.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        return (
            StageHandlerRegistration(
                capability=StageCapability(
                    kind="test.echo_candidate",
                    inputs=(CapabilityInput(name="candidate", contracts=("candidate/1.0",)),),
                    outputs=("candidate/1.0",),
                ),
                factory=lambda _stage, _services: _EchoCandidateHandler(),
            ),
        )


def test_api_executes_normalized_workflow_and_persists_run_state(tmp_path: Path) -> None:
    migrate.upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="api-execute", name="API execute")
        session.add(project)
        session.flush()
        project_id = project.id
    engine.dispose()

    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "Echo candidate",
        "inputs": {"candidate": {"contract": "candidate/1.0"}},
        "stages": [
            {
                "id": "echo",
                "kind": "test.echo_candidate",
                "input_contracts": {"candidate": "candidate/1.0"},
                "input_bindings": {"candidate": "$candidate"},
                "output_contract": "candidate/1.0",
                "params": {},
            }
        ],
        "outputs": {"candidate": "echo"},
    }
    candidate = Candidate(id=new_ulid(), compound_id=new_ulid(), project_id=project_id)
    run_id = str(new_ulid())
    app = create_app(
        data_root=tmp_path,
        token="test-secret",  # noqa: S106
        stage_registry=StageHandlerRegistry([_EchoCandidatePlugin()]),
    )
    headers = {"Authorization": "Bearer test-secret"}
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{project_id}/runs/{run_id}/execute",
            headers=headers,
            json={"workflow": workflow, "inputs": {"candidate": candidate.model_dump(mode="json")}},
        )
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        deadline = monotonic() + 5
        status_response = client.get(
            f"/v1/projects/{project_id}/runs/{run_id}/status", headers=headers
        )
        while status_response.json()["status"] not in {"succeeded", "failed"}:
            assert monotonic() < deadline, status_response.json()
            sleep(0.01)
            status_response = client.get(
                f"/v1/projects/{project_id}/runs/{run_id}/status", headers=headers
            )
        assert status_response.json()["status"] == "succeeded"
        assert status_response.json()["submission"]["state"] == "succeeded"
        assert status_response.json()["tasks"][0]["state"] == "succeeded"
        repeated = client.post(
            f"/v1/projects/{project_id}/runs/{run_id}/execute",
            headers=headers,
            json={"workflow": workflow, "inputs": {"candidate": candidate.model_dump(mode="json")}},
        )
        assert repeated.status_code == 409


class _ProcessCandidateHandler(_EchoCandidateHandler):
    started = Event()

    def __init__(self, executor: object, log_dir: Path) -> None:
        self.executor = executor
        self.log_dir = log_dir

    def execute(self, invocation: TaskInvocation) -> Candidate:
        self.started.set()
        self.executor.start(
            CommandSpec(
                argv=(
                    sys.executable,
                    "-c",
                    "import time; print('started', flush=True); time.sleep(30)",
                ),
                cwd=self.log_dir.parent,
            ),
            log_dir=self.log_dir,
        ).wait(timeout=40)
        return super().execute(invocation)


class _ProcessCandidatePlugin(_EchoCandidatePlugin):
    plugin_id = "tests.process_candidate"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        registration = super().registrations()[0]
        capability = registration.capability.model_copy(update={"kind": "test.process_candidate"})
        return (
            StageHandlerRegistration(
                capability=capability,
                factory=lambda _stage, services: _ProcessCandidateHandler(
                    services.executor, services.run_root / "process-cancel"
                ),
            ),
        )


def test_api_cancel_terminates_active_local_process(tmp_path: Path) -> None:
    _ProcessCandidateHandler.started = Event()
    migrate.upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="api-cancel", name="API cancel")
        session.add(project)
        session.flush()
        project_id = project.id
    engine.dispose()

    workflow = {
        "schema": "caddsuite.workflow/1",
        "name": "Cancelable process",
        "inputs": {"candidate": {"contract": "candidate/1.0"}},
        "stages": [
            {
                "id": "execute",
                "kind": "test.process_candidate",
                "input_contracts": {"candidate": "candidate/1.0"},
                "input_bindings": {"candidate": "$candidate"},
                "output_contract": "candidate/1.0",
                "params": {},
            }
        ],
        "outputs": {"candidate": "execute"},
    }
    candidate = Candidate(id=new_ulid(), compound_id=new_ulid(), project_id=project_id)
    run_id = str(new_ulid())
    app = create_app(
        data_root=tmp_path,
        token="test-secret",  # noqa: S106
        stage_registry=StageHandlerRegistry([_ProcessCandidatePlugin()]),
    )
    headers = {"Authorization": "Bearer test-secret"}
    with TestClient(app) as client:
        submitted = client.post(
            f"/v1/projects/{project_id}/runs/{run_id}/execute",
            headers=headers,
            json={"workflow": workflow, "inputs": {"candidate": candidate.model_dump(mode="json")}},
        )
        assert submitted.status_code == 202
        assert _ProcessCandidateHandler.started.wait(timeout=3)
        cancellation = client.post(
            f"/v1/projects/{project_id}/runs/{run_id}/cancel", headers=headers
        )
        assert cancellation.status_code == 202
        deadline = monotonic() + 5
        status_response = client.get(
            f"/v1/projects/{project_id}/runs/{run_id}/status", headers=headers
        )
        while status_response.json()["status"] not in {"stopped", "failed"}:
            assert monotonic() < deadline, status_response.json()
            sleep(0.01)
            status_response = client.get(
                f"/v1/projects/{project_id}/runs/{run_id}/status", headers=headers
            )
        assert status_response.json()["status"] == "stopped"
        assert status_response.json()["submission"]["cancel_requested"] is True
        assert status_response.json()["tasks"][0]["state"] == "cancelled"
        with app.state.sessions() as session:
            attempt = session.query(TaskAttemptRow).one()
            assert attempt.exit_status == "cancelled"
            assert len(attempt.steps or []) == 1


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
        events = client.get(f"/v1/projects/{project_id}/runs/{run_id}/events", headers=headers)
        assert events.status_code == 200
        assert "event: run-status" in events.text
        assert '"status":"succeeded"' in events.text

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


def test_project_artifact_upload_streams_to_cas_with_size_limit(tmp_path: Path) -> None:
    project_id, _run_id, _attempt_id = _seed_project_run(tmp_path)
    app = create_app(data_root=tmp_path, token="test-secret", max_upload_bytes=16)  # noqa: S106
    headers = {
        "Authorization": "Bearer test-secret",
        "Content-Type": "chemical/x-mdl-sdfile",
        "X-Artifact-Role": "ligand_input",
        "X-Filename": r"C:\fakepath\ligand.sdf",
    }
    content = b"ligand structure"
    with TestClient(app) as client:
        uploaded = client.post(
            f"/v1/projects/{project_id}/artifacts", headers=headers, content=content
        )
        assert uploaded.status_code == 201, uploaded.text
        data = uploaded.json()
        assert data["artifact"]["role"] == "ligand_input"
        assert data["artifact"]["sha256"] == hashlib.sha256(content).hexdigest()
        assert data["size_bytes"] == len(content)
        assert data["created"] is True

        duplicate = client.post(
            f"/v1/projects/{project_id}/artifacts", headers=headers, content=content
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["artifact"]["artifact_id"] == data["artifact"]["artifact_id"]
        assert duplicate.json()["created"] is False

        too_large = client.post(
            f"/v1/projects/{project_id}/artifacts",
            headers=headers,
            content=content + b"x",
        )
        assert too_large.status_code == 413
        with app.state.sessions() as session:
            artifact = session.get(ArtifactRow, data["artifact"]["artifact_id"])
            assert artifact is not None
            assert artifact.original_name == "ligand.sdf"
            assert artifact.media_type == "chemical/x-mdl-sdfile"
            link = session.get(ProjectArtifactRow, (project_id, artifact.id, "ligand_input"))
            assert link is not None
            assert (
                session.scalar(
                    select(ArtifactRow).where(
                        ArtifactRow.sha256 == hashlib.sha256(content + b"x").hexdigest()
                    )
                )
                is None
            )


def test_provenance_api_requires_nonempty_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="token must be configured"):
        create_app(data_root=tmp_path, token="")
