"""Recorded MD choices use task provenance, never project-wide filename guesses."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.api.provenance import create_app
from caddsuite.application.trajectory_options import recorded_trajectory_options
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import MDStageKind, MDStageResult
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import (
    ProjectArtifactRow,
    ProjectRow,
    TaskCacheRow,
    TaskRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import artifacts_root, database_path


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[tuple[sessionmaker[Session], ArtifactStore]]:
    upgrade(database_path(tmp_path))
    engine = create_db_engine(database_path(tmp_path))
    yield make_session_factory(engine), ArtifactStore(artifacts_root(tmp_path))
    engine.dispose()


def _seed(
    session: Session,
    store: ArtifactStore,
    *,
    project_id: str | None = None,
    state: str = "succeeded",
    names: tuple[str, ...] = ("production.gro", "production.xtc", "topol.top"),
    visible: bool = True,
    valid_hash: bool = True,
) -> tuple[str, str, dict[str, str]]:
    if project_id is None:
        project = ProjectRow(slug=new_ulid(), name="Explicit trajectory metadata fixture")
        session.add(project)
        session.flush()
        project_id = project.id
    run = WorkflowRunRow(
        project_id=project_id,
        accession=new_ulid(),
        workflow_hash="a" * 64,
        config_hash="b" * 64,
        status=state,
    )
    session.add(run)
    session.flush()
    task = TaskRow(run_id=run.id, stage_id="md", state=state, cache_key=new_ulid().ljust(64, "0"))
    session.add(task)
    session.flush()
    refs: dict[str, ArtifactRef] = {}
    ids: dict[str, str] = {}
    for name in names:
        blob = store.put_bytes(f"Metadata fixture only: {name}/{new_ulid()}".encode())
        artifact = register_blob(
            session, blob, kind="output", media_type="application/octet-stream", original_name=name
        )
        if visible:
            session.add(
                ProjectArtifactRow(project_id=project_id, artifact_id=artifact.id, role="output")
            )
        refs[name] = ArtifactRef(
            artifact_id=artifact.id, role="output", sha256=blob.sha256 if valid_hash else "f" * 64
        )
        ids[name] = artifact.id
    if names:
        refs["duplicate_alias"] = refs[names[0]]
    result = MDStageResult(
        id=new_ulid(),
        system_id=new_ulid(),
        stage_input_id=new_ulid(),
        stage_index=0,
        stage_kind=MDStageKind.PRODUCTION,
        engine=SoftwareRef(name="fixture", version="1", kind="engine"),
        adapter=SoftwareRef(name="fixture", version="1", kind="adapter"),
        parameters={},
        runtime_seconds=1,
        artifacts=refs,
    )
    session.add(
        TaskCacheRow(
            cache_key=task.cache_key,
            schema_version=result.schema_version,
            payload=result.model_dump(mode="json"),
            source_task_id=task.id,
        )
    )
    session.flush()
    return project_id, task.id, ids


def test_choices_are_exact_per_task_and_exclude_include_topologies(storage) -> None:
    sessions, store = storage
    with sessions.begin() as session:
        project_id, first, first_ids = _seed(session, store)
        _, second, second_ids = _seed(session, store, project_id=project_id)
        _seed(session, store)  # Another project must never appear.
        choices = recorded_trajectory_options(session, project_id)
        assert len(choices) == 2
        by_task = {item["task_id"]: item for item in choices}
        for task, ids in [(first, first_ids), (second, second_ids)]:
            assert [a["id"] for a in by_task[task]["topologies"]] == [ids["production.gro"]]
            assert [a["id"] for a in by_task[task]["trajectories"]] == [ids["production.xtc"]]


@pytest.mark.parametrize(
    "override",
    [
        {"state": "failed"},
        {"state": "running"},
        {"valid_hash": False},
        {"visible": False},
        {"names": ("topol.top", "production.xtc")},
        {"names": ("production.gro",)},
    ],
)
def test_incomplete_failed_unscoped_or_changed_outputs_are_not_suggested(storage, override) -> None:
    sessions, store = storage
    with sessions.begin() as session:
        project_id, _, _ = _seed(session, store, **override)
        assert recorded_trajectory_options(session, project_id) == []


def test_dashboard_trajectory_choices_are_authenticated_and_project_scoped(
    storage, tmp_path: Path
) -> None:
    sessions, store = storage
    with sessions.begin() as session:
        first, _, first_ids = _seed(session, store)
        second, _, second_ids = _seed(session, store)
    app = create_app(data_root=tmp_path, token="test-secret")  # noqa: S106
    with TestClient(app) as client:
        assert client.get(f"/v1/projects/{first}/dashboard").status_code == 401
        for project_id, ids in [(first, first_ids), (second, second_ids)]:
            response = client.get(
                f"/v1/projects/{project_id}/dashboard",
                headers={"Authorization": "Bearer test-secret"},
            )
            assert response.status_code == 200
            pairs = response.json()["trajectory_options"]
            assert len(pairs) == 1
            assert pairs[0]["topologies"][0]["id"] == ids["production.gro"]
