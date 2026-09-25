"""Task attempt persistence for PROV activities, environments, software and artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.execution import (
    AttemptArtifact,
    AttemptSoftware,
    AttemptStatus,
    EnvironmentKind,
    ErrorRecord,
    HostInfo,
    PlatformRef,
    SoftwareEnvironment,
    StepRecord,
    TaskAttempt,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind, TaskState
from caddsuite.domain.identity import new_ulid
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.attempts import AttemptConflict, TaskAttemptStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import (
    AttemptAgentRow,
    AttemptArtifactRow,
    ProjectRow,
    SoftwareEnvironmentRow,
    TaskAttemptRow,
    WorkflowRunRow,
)
from caddsuite.storage.provenance_graph import attempt_lineage
from caddsuite.storage.task_state import TaskStateStore


@pytest.fixture
def attempt_context(tmp_path: Path) -> Iterator[tuple[TaskAttemptStore, object, object, Session]]:
    db_path = tmp_path / "attempt.db"
    migrate.upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="attempt-demo", name="Attempt Demo")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN0001",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    task_store = TaskStateStore(sessions)
    task = task_store.create(run_id=run_id, stage_id="qm")
    task = task_store.transition(
        task.id,
        expected=task.state,
        target=__import__("caddsuite.domain.enums", fromlist=["TaskState"]).TaskState.READY,
        expected_version=task.version,
    )
    task = task_store.transition(
        task.id,
        expected=task.state,
        target=TaskState.RUNNING,
        expected_version=task.version,
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    input_blob = artifacts.put_bytes(b"registered input")
    output_blob = artifacts.put_bytes(b"registered output")
    with sessions.begin() as session:
        input_row = register_blob(
            session, input_blob, kind="structure", media_type="chemical/x-mdl-sdfile"
        )
        output_row = register_blob(
            session, output_blob, kind="qm_result", media_type="application/json"
        )
        input_ref = ArtifactRef(
            artifact_id=input_row.id,
            role="input",
            sha256=input_row.sha256,
        )
        output_ref = ArtifactRef(
            artifact_id=output_row.id,
            role="result",
            sha256=output_row.sha256,
        )
    context = (TaskAttemptStore(sessions), task, (input_ref, output_ref), sessions)
    try:
        yield context
    finally:
        engine.dispose()


def _running_attempt(task_id: str, input_ref: ArtifactRef) -> TaskAttempt:
    now = datetime.now(UTC)
    return TaskAttempt(
        id=new_ulid(),
        task_id=task_id,
        attempt_no=1,
        executor="local",
        host=HostInfo(
            hostname="test-host",
            os="Linux",
            kernel="test-kernel",
            machine="x86_64",
            is_wsl=True,
            logical_cpus=8,
        ),
        platform=PlatformRef(version="0.1.0", git_commit="a" * 40, git_dirty=True),
        software=(
            AttemptSoftware(
                role="engine",
                software=SoftwareRef(
                    name="PySCF",
                    version="2.14.0",
                    kind=SoftwareKind.ENGINE,
                    license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
                ),
            ),
        ),
        environment=SoftwareEnvironment(
            id=new_ulid(),
            kind=EnvironmentKind.CONDA,
            name="caddsuite-pyscf",
            prefix="/envs/caddsuite-pyscf",
            lock_sha256="c" * 64,
            key_packages={"python": "3.12", "pyscf": "2.14.0"},
            captured_at=now,
        ),
        artifacts=(AttemptArtifact(artifact=input_ref, direction="used", role="geometry"),),
        started_at=now,
        status=AttemptStatus.RUNNING,
    )


def test_attempt_store_persists_and_finalizes_provenance_edges(attempt_context) -> None:
    store, task, refs, sessions = attempt_context
    input_ref, output_ref = refs
    attempt = store.begin(_running_attempt(task.id, input_ref))
    step = StepRecord(
        argv=("/envs/caddsuite-pyscf/bin/python", "-m", "caddsuite_worker.pyscf_worker"),
        cwd="/tmp/task",
        env_subset={"CONDA_PREFIX": "/envs/caddsuite-pyscf", "API_TOKEN": "[REDACTED]"},
        pid=1234,
        process_start_time=123.0,
        exit_code=0,
    )
    completed = store.finish(
        str(attempt.id),
        status=AttemptStatus.SUCCEEDED,
        ended_at=datetime.now(UTC),
        steps=(step,),
        generated_artifacts=(
            AttemptArtifact(artifact=output_ref, direction="generated", role="normalized_result"),
        ),
    )
    assert completed.status is AttemptStatus.SUCCEEDED
    assert completed.environment is not None
    assert completed.software[0].software.version == "2.14.0"
    assert store.get(str(attempt.id)) == completed
    lineage = attempt_lineage(sessions, str(attempt.id))
    assert lineage["root_attempt_id"] == str(attempt.id)
    assert [item["id"] for item in lineage["attempts"]] == [str(attempt.id)]
    assert {(edge["direction"], edge["role"]) for edge in lineage["edges"]} == {
        ("used", "geometry"),
        ("generated", "normalized_result"),
    }
    with sessions() as session:
        row = session.get(TaskAttemptRow, str(attempt.id))
        assert row is not None
        assert row.exit_status == "succeeded"
        assert row.environment_id == str(completed.environment.id)
        assert len(session.scalars(select(AttemptAgentRow)).all()) == 1
        links = session.scalars(select(AttemptArtifactRow)).all()
        assert {(link.direction, link.role) for link in links} == {
            ("used", "geometry"),
            ("generated", "normalized_result"),
        }
        environment = session.get(SoftwareEnvironmentRow, str(completed.environment.id))
        assert environment is not None
        assert environment.lock_sha256 == "c" * 64


def test_failed_attempt_requires_error_and_cannot_be_finalized_twice(attempt_context) -> None:
    store, task, refs, _sessions = attempt_context
    attempt = store.begin(_running_attempt(task.id, refs[0]))
    with pytest.raises(ValueError, match="failed attempts require"):
        store.finish(
            str(attempt.id),
            status=AttemptStatus.FAILED,
            ended_at=datetime.now(UTC),
            steps=(),
        )
    error = ErrorRecord(
        code="QM.SCF.NONCONVERGENCE",
        message="SCF failed to converge",
        stage_id="qm",
        task_id=task.id,
        retryable=False,
    )
    failed = store.finish(
        str(attempt.id),
        status=AttemptStatus.FAILED,
        ended_at=datetime.now(UTC),
        steps=(),
        error=error,
    )
    assert failed.error == error
    with pytest.raises(AttemptConflict, match="already terminal"):
        store.finish(
            str(attempt.id),
            status=AttemptStatus.CANCELLED,
            ended_at=datetime.now(UTC),
            steps=(),
        )
