"""Tests for project deletion, cascade cleanup, API endpoint, and CLI command."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from caddsuite.api.provenance import create_app
from caddsuite.chem.standardize import make_compound, standardize_smiles
from caddsuite.cli.main import app as cli_app
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.execution import AttemptArtifact, AttemptStatus
from caddsuite.contracts.registry import InputRecord
from caddsuite.domain.enums import TaskState
from caddsuite.domain.identity import new_ulid
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.compound_registry import CompoundRegistry
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import (
    AccessionCounterRow,
    AttemptAgentRow,
    AttemptArtifactRow,
    CompoundFormRow,
    CompoundInputRow,
    CompoundRow,
    DecisionRow,
    ProjectArtifactRow,
    ProjectRow,
    ResultRow,
    RunSubmissionRow,
    TaskAttemptRow,
    TaskCacheRow,
    TaskRow,
    TaskStateEventRow,
    ValidationIssueRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import artifacts_root, database_path
from caddsuite.storage.projects import delete_project
from caddsuite.storage.task_state import TaskStateStore
from tests.unit.test_attempt_store import _running_attempt

runner = CliRunner()


def _seed_complete_project(root: Path) -> tuple[str, str, str, str]:
    """Seed a project with runs, tasks, attempts, results, artifacts, and compounds."""
    migrate.upgrade(database_path(root))
    engine = create_db_engine(database_path(root))
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="cascade-demo", name="Cascade Demo")
        session.add(project)
        session.flush()
        project_id = project.id

        run = WorkflowRunRow(
            project_id=project_id,
            accession="RUN-DEL-001",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="succeeded",
        )
        session.add(run)
        session.flush()
        run_id = run.id

    task_store = TaskStateStore(sessions)
    task = task_store.create(run_id=run_id, stage_id="standardize")
    task = task_store.transition(
        task.id, expected=task.state, target=TaskState.READY, expected_version=task.version
    )
    task = task_store.transition(
        task.id, expected=task.state, target=TaskState.RUNNING, expected_version=task.version
    )

    artifacts = ArtifactStore(artifacts_root(root))
    input_blob = artifacts.put_bytes(b"project input artifact")
    output_blob = artifacts.put_bytes(b"project output artifact")
    with sessions.begin() as session:
        input_row = register_blob(session, input_blob, kind="input", media_type="application/json")
        output_row = register_blob(
            session, output_blob, kind="output", media_type="application/json"
        )
        project_art = ProjectArtifactRow(
            project_id=project_id,
            artifact_id=input_row.id,
            role="test-purpose",
        )
        session.add(project_art)

    attempt_store = TaskAttemptStore(sessions)
    attempt = attempt_store.begin(
        _running_attempt(
            task.id,
            ArtifactRef(artifact_id=input_row.id, role="input", sha256=input_row.sha256),
        )
    )
    attempt_store.finish(
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

    task = task_store.transition(
        task.id, expected=task.state, target=TaskState.SUCCEEDED, expected_version=task.version
    )

    registry = CompoundRegistry(sessions)
    ethanol = "CCO"
    std = standardize_smiles(ethanol)
    inp = InputRecord(source="manual", original_text=ethanol)
    reg_res = registry.register(
        project_id=project_id,
        inchikey=std.identity.inchikey,
        input_record=inp,
        create_compound=lambda acc: make_compound(
            std,
            compound_id=new_ulid(),
            project_id=project_id,
            accession=acc,
            name="Ethanol",
            original_text=ethanol,
            source="manual",
        ),
    )

    with sessions.begin() as session:
        res = ResultRow(
            project_id=project_id,
            attempt_id=str(attempt.id),
            contract="property_prediction",
            schema_version="1",
            payload={"mw": 46.07},
            primary_value=46.07,
            primary_unit="g/mol",
        )
        session.add(res)

    engine.dispose()
    return project_id, run_id, task.id, reg_res.compound.id


def test_delete_project_storage_empty(tmp_path: Path) -> None:
    db = database_path(tmp_path)
    migrate.upgrade(db)
    engine = create_db_engine(db)
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        p = ProjectRow(slug="empty-proj", name="Empty")
        session.add(p)
        session.flush()
        pid = p.id

    with sessions.begin() as session:
        assert delete_project(session, pid) is True

    with sessions() as session:
        assert session.get(ProjectRow, pid) is None

    with sessions.begin() as session:
        assert delete_project(session, pid) is False
        assert delete_project(session, "nonexistent-id") is False
    engine.dispose()


def test_delete_project_storage_cascade(tmp_path: Path) -> None:
    project_id, run_id, task_id, compound_id = _seed_complete_project(tmp_path)
    engine = create_db_engine(database_path(tmp_path))
    sessions = make_session_factory(engine)

    with sessions.begin() as session:
        deleted = delete_project(session, project_id)
        assert deleted is True

    with sessions() as session:
        assert session.get(ProjectRow, project_id) is None
        assert (
            list(
                session.scalars(
                    select(WorkflowRunRow).where(WorkflowRunRow.project_id == project_id)
                )
            )
            == []
        )
        assert list(session.scalars(select(TaskRow).where(TaskRow.run_id == run_id))) == []
        assert (
            list(session.scalars(select(TaskAttemptRow).where(TaskAttemptRow.task_id == task_id)))
            == []
        )
        assert list(session.scalars(select(AttemptAgentRow))) == []
        assert list(session.scalars(select(AttemptArtifactRow))) == []
        assert (
            list(session.scalars(select(ResultRow).where(ResultRow.project_id == project_id))) == []
        )
        assert (
            list(session.scalars(select(DecisionRow).where(DecisionRow.task_id == task_id))) == []
        )
        assert (
            list(
                session.scalars(
                    select(ValidationIssueRow).where(ValidationIssueRow.task_id == task_id)
                )
            )
            == []
        )
        assert (
            list(
                session.scalars(select(TaskCacheRow).where(TaskCacheRow.source_task_id == task_id))
            )
            == []
        )
        assert (
            list(
                session.scalars(
                    select(TaskStateEventRow).where(TaskStateEventRow.task_id == task_id)
                )
            )
            == []
        )
        assert (
            list(
                session.scalars(
                    select(ProjectArtifactRow).where(ProjectArtifactRow.project_id == project_id)
                )
            )
            == []
        )
        assert (
            list(
                session.scalars(
                    select(AccessionCounterRow).where(AccessionCounterRow.project_id == project_id)
                )
            )
            == []
        )
        assert (
            list(session.scalars(select(CompoundRow).where(CompoundRow.project_id == project_id)))
            == []
        )
        assert (
            list(
                session.scalars(
                    select(CompoundInputRow).where(CompoundInputRow.compound_id == compound_id)
                )
            )
            == []
        )
        assert (
            list(
                session.scalars(
                    select(CompoundFormRow).where(CompoundFormRow.compound_id == compound_id)
                )
            )
            == []
        )
        assert (
            list(session.scalars(select(RunSubmissionRow).where(RunSubmissionRow.run_id == run_id)))
            == []
        )
    engine.dispose()


def test_api_delete_project(tmp_path: Path) -> None:
    project_id, _, _, _ = _seed_complete_project(tmp_path)
    app = create_app(
        data_root=tmp_path,
        token="test-secret",  # noqa: S106
        allowed_origins=("http://127.0.0.1:5173",),
    )
    headers = {
        "Authorization": "Bearer test-secret",
        "Origin": "http://127.0.0.1:5173",
    }
    with TestClient(app) as client:
        # Unauthorized without token
        unauth = client.delete(f"/v1/projects/{project_id}")
        assert unauth.status_code == 401

        # CORS preflight for DELETE
        preflight = client.options(
            f"/v1/projects/{project_id}",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert preflight.status_code == 200
        assert "DELETE" in preflight.headers.get("access-control-allow-methods", "")

        # Delete nonexistent project returns 404
        not_found = client.delete("/v1/projects/nonexistent-project", headers=headers)
        assert not_found.status_code == 404

        # Delete existing project returns 204
        success = client.delete(f"/v1/projects/{project_id}", headers=headers)
        assert success.status_code == 204

        # Verify project is no longer listed
        projects_res = client.get("/v1/projects", headers=headers)
        assert projects_res.status_code == 200
        pids = [p["id"] for p in projects_res.json()]
        assert project_id not in pids

        # Attempting to delete again returns 404
        again = client.delete(f"/v1/projects/{project_id}", headers=headers)
        assert again.status_code == 404


def test_cli_project_delete_by_slug_and_id(tmp_path: Path) -> None:
    # Create project 1
    c1 = runner.invoke(
        cli_app,
        ["project", "create", "test-slug-1", "--name", "Test Slug 1", "--data-root", str(tmp_path)],
    )
    assert c1.exit_code == 0
    _ = json.loads(c1.output)

    # Create project 2
    c2 = runner.invoke(
        cli_app,
        ["project", "create", "test-slug-2", "--name", "Test Slug 2", "--data-root", str(tmp_path)],
    )
    assert c2.exit_code == 0
    p2 = json.loads(c2.output)

    # Delete project 1 by slug
    del1 = runner.invoke(
        cli_app,
        ["project", "delete", "test-slug-1", "--data-root", str(tmp_path)],
    )
    assert del1.exit_code == 0
    assert "Deleted project test-slug-1" in del1.output

    # List projects - only project 2 remains
    listed = runner.invoke(cli_app, ["project", "list", "--data-root", str(tmp_path)])
    assert listed.exit_code == 0
    items = json.loads(listed.output)
    assert len(items) == 1
    assert items[0]["id"] == p2["id"]

    # Delete project 2 by ID
    del2 = runner.invoke(
        cli_app,
        ["project", "delete", p2["id"], "--data-root", str(tmp_path)],
    )
    assert del2.exit_code == 0

    # List projects - empty now
    listed2 = runner.invoke(cli_app, ["project", "list", "--data-root", str(tmp_path)])
    assert listed2.exit_code == 0
    assert json.loads(listed2.output) == []

    # Deleting nonexistent returns error
    del_missing = runner.invoke(
        cli_app,
        ["project", "delete", "no-such-project", "--data-root", str(tmp_path)],
    )
    assert del_missing.exit_code == 2
    assert "not found" in del_missing.output
