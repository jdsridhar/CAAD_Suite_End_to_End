from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.domain.enums import TaskState
from caddsuite.storage import migrate
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.decisions import DecisionStore
from caddsuite.storage.models import (
    DecisionRow,
    ProjectRow,
    TaskStateEventRow,
    WorkflowRunRow,
)
from caddsuite.storage.task_state import TaskStateConflict, TaskStateStore
from caddsuite.validation.decisions import Decision, DecisionOption, DecisionRequest, DecisionScope


@pytest.fixture
def decision_env(
    tmp_path: Path,
) -> Iterator[tuple[DecisionStore, TaskStateStore, sessionmaker[Session], str]]:
    db_path = tmp_path / "decisions.db"
    migrate.upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="decision-test", name="Decision test")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-20260924-002",
            workflow_hash="d" * 64,
            config_hash="e" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    yield DecisionStore(sessions), TaskStateStore(sessions), sessions, run_id
    engine.dispose()


def _waiting_task(task_states: TaskStateStore, run_id: str) -> tuple[str, int]:
    task = task_states.create(run_id=run_id, stage_id="review")
    for target in (
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.AWAITING_DECISION,
    ):
        task = task_states.transition(
            task.id,
            expected=task.state,
            target=target,
            expected_version=task.version,
        )
    return task.id, task.version


def _decision() -> Decision:
    request = DecisionRequest(
        issue_code="STRUCTURE.SITE_AMBIGUOUS",
        question="Which site preparation should be used?",
        options=(
            DecisionOption(
                key="provide_site",
                label="Provide a binding site",
                consequence="Use the supplied site coordinates.",
            ),
            DecisionOption(
                key="blind",
                label="Use a blind docking box",
                consequence="Search the whole receptor using the configured box.",
            ),
        ),
    )
    return Decision(
        request=request,
        chosen_key="provide_site",
        decided_by="researcher",
        decided_at=datetime.now(UTC),
        scope=DecisionScope.TASK,
        rationale="Use the experimentally supported site.",
    )


def test_decision_and_resume_transition_commit_atomically(decision_env) -> None:
    decisions, task_states, sessions, run_id = decision_env
    task_id, version = _waiting_task(task_states, run_id)
    result = decisions.submit(task_id, _decision(), expected_version=version)
    task = task_states.get(task_id)
    assert result.task_id == task_id
    assert result.state is TaskState.READY
    assert result.version == version + 1
    assert task.state is TaskState.READY
    assert task.version == version + 1

    with sessions() as session:
        row = session.scalar(select(DecisionRow).where(DecisionRow.task_id == task_id))
        assert row is not None
        assert row.chosen_key == "provide_site"
        assert row.payload["rationale"] == "Use the experimentally supported site."
        events = tuple(
            session.scalars(
                select(TaskStateEventRow)
                .where(TaskStateEventRow.task_id == task_id)
                .order_by(TaskStateEventRow.version)
            )
        )
        assert events[-1].from_state == TaskState.AWAITING_DECISION.value
        assert events[-1].to_state == TaskState.READY.value
        assert events[-1].reason == "decision selected: provide_site"


def test_stale_decision_does_not_write_record_or_resume_task(decision_env) -> None:
    decisions, task_states, sessions, run_id = decision_env
    task_id, version = _waiting_task(task_states, run_id)
    with pytest.raises(TaskStateConflict):
        decisions.submit(task_id, _decision(), expected_version=version - 1)
    assert task_states.get(task_id).state is TaskState.AWAITING_DECISION
    assert len(task_states.history(task_id)) == 4
    with sessions() as session:
        assert session.scalar(select(DecisionRow.id).where(DecisionRow.task_id == task_id)) is None


def test_decision_cannot_resume_a_task_that_is_not_waiting(decision_env) -> None:
    decisions, task_states, sessions, run_id = decision_env
    task = task_states.create(run_id=run_id, stage_id="review")
    with pytest.raises(TaskStateConflict):
        decisions.submit(task.id, _decision(), expected_version=task.version)
    assert task_states.get(task.id).state is TaskState.PENDING
    with sessions() as session:
        assert session.scalar(select(DecisionRow.id).where(DecisionRow.task_id == task.id)) is None
