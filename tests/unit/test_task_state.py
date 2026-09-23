from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from caddsuite.domain.enums import TaskState
from caddsuite.storage import migrate
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.storage.task_state import (
    TaskNotFound,
    TaskStateConflict,
    TaskStateStore,
)
from caddsuite.workflow.state import InvalidTaskTransition


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "state.db"
    migrate.upgrade(path)
    return path


@pytest.fixture
def task_store(db_path: Path) -> Iterator[tuple[TaskStateStore, str]]:
    engine = create_db_engine(db_path)
    sessions: sessionmaker = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="state-test", name="Task state test")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-20260924-001",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    yield TaskStateStore(sessions), run_id
    engine.dispose()


def _create(store_and_run: tuple[TaskStateStore, str], cache_key: str | None = None):
    store, run_id = store_and_run
    return store.create(
        run_id=run_id,
        stage_id="dock",
        subject_kind="compound",
        subject_id="01J8ZZZZZZZZZZZZZZZZZZZZZZ",
        cache_key=cache_key,
    )


def test_task_state_transitions_persist_with_ordered_history(task_store) -> None:
    store, _run_id = task_store
    task = _create(task_store)
    assert task.state is TaskState.PENDING
    assert task.version == 0

    for target in (TaskState.READY, TaskState.RUNNING, TaskState.SUCCEEDED):
        task = store.transition(
            task.id,
            expected=task.state,
            target=target,
            expected_version=task.version,
        )

    assert store.get(task.id).state is TaskState.SUCCEEDED
    history = store.history(task.id)
    assert [event.version for event in history] == [0, 1, 2, 3]
    assert [event.to_state for event in history] == [
        TaskState.PENDING,
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.SUCCEEDED,
    ]
    assert history[0].from_state is None


def test_decision_pause_and_crash_interruption_can_resume(task_store) -> None:
    store, _run_id = task_store
    task = _create(task_store)
    for target in (
        TaskState.READY,
        TaskState.AWAITING_DECISION,
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.INTERRUPTED,
        TaskState.READY,
    ):
        task = store.transition(
            task.id,
            expected=task.state,
            target=target,
            expected_version=task.version,
            reason="test lifecycle",
        )
    assert task.state is TaskState.READY
    assert task.version == 6


def test_illegal_and_stale_transitions_do_not_change_state_or_history(task_store) -> None:
    store, _run_id = task_store
    task = _create(task_store)
    with pytest.raises(InvalidTaskTransition, match="cannot transition"):
        store.transition(
            task.id,
            expected=TaskState.PENDING,
            target=TaskState.SUCCEEDED,
            expected_version=0,
        )
    assert len(store.history(task.id)) == 1

    ready = store.transition(
        task.id,
        expected=TaskState.PENDING,
        target=TaskState.READY,
        expected_version=0,
    )
    with pytest.raises(TaskStateConflict, match="version 1"):
        store.transition(
            task.id,
            expected=TaskState.PENDING,
            target=TaskState.CANCELLED,
            expected_version=0,
        )
    assert store.get(task.id) == ready
    assert len(store.history(task.id)) == 2


def test_failed_and_cached_tasks_can_be_explicitly_requeued(task_store) -> None:
    store, _run_id = task_store
    task = _create(task_store)
    task = store.transition(
        task.id, expected=TaskState.PENDING, target=TaskState.READY, expected_version=0
    )
    task = store.transition(
        task.id, expected=TaskState.READY, target=TaskState.CACHED, expected_version=1
    )
    task = store.transition(
        task.id,
        expected=TaskState.CACHED,
        target=TaskState.PENDING,
        expected_version=2,
        reason="user requested a fresh run",
    )
    assert task.state is TaskState.PENDING
    assert task.version == 3


def test_store_reports_missing_tasks_and_rejects_blank_reasons(task_store) -> None:
    store, _run_id = task_store
    with pytest.raises(TaskNotFound):
        store.get("01J8ZZZZZZZZZZZZZZZZZZZZZZ")
    task = _create(task_store)
    with pytest.raises(ValueError, match="must not be blank"):
        store.transition(
            task.id,
            expected=TaskState.PENDING,
            target=TaskState.READY,
            expected_version=0,
            reason="   ",
        )


def test_running_task_can_pause_for_a_decision(task_store) -> None:
    store, _run_id = task_store
    task = _create(task_store)
    for target in (
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.AWAITING_DECISION,
        TaskState.READY,
    ):
        task = store.transition(
            task.id,
            expected=task.state,
            target=target,
            expected_version=task.version,
            reason="awaiting scientific review",
        )
    assert task.state is TaskState.READY


def test_task_cache_key_is_persisted_and_validated(task_store) -> None:
    store, _run_id = task_store
    cache_key = "c" * 64
    task = _create(task_store, cache_key=cache_key)
    assert task.cache_key == cache_key
    assert store.get(task.id).cache_key == cache_key
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _create(task_store, cache_key="not-a-digest")


def test_rerun_resets_a_task_set_and_invalidates_cache_keys(task_store) -> None:
    store, run_id = task_store
    dock = store.create(run_id=run_id, stage_id="dock", cache_key="a" * 64)
    analysis = store.create(run_id=run_id, stage_id="analysis", cache_key="b" * 64)
    for task in (dock, analysis):
        for target in (TaskState.READY, TaskState.RUNNING, TaskState.SUCCEEDED):
            task = store.transition(
                task.id,
                expected=task.state,
                target=target,
                expected_version=task.version,
            )
    reset = store.reset_for_rerun([dock.id, analysis.id], reason="rerun from docking")
    assert {task.state for task in reset} == {TaskState.PENDING}
    assert {task.cache_key for task in reset} == {None}
    assert {task.version for task in reset} == {4}
    assert len(store.history(dock.id)) == 5
    assert store.history(dock.id)[-1].reason == "rerun from docking"


def test_rerun_plan_validation_prevents_partial_reset(task_store) -> None:
    store, run_id = task_store
    completed = store.create(run_id=run_id, stage_id="dock", cache_key="a" * 64)
    active = store.create(run_id=run_id, stage_id="analysis", cache_key="b" * 64)
    completed = store.transition(
        completed.id,
        expected=TaskState.PENDING,
        target=TaskState.READY,
        expected_version=0,
    )
    completed = store.transition(
        completed.id,
        expected=TaskState.READY,
        target=TaskState.RUNNING,
        expected_version=1,
    )
    completed = store.transition(
        completed.id,
        expected=TaskState.RUNNING,
        target=TaskState.SUCCEEDED,
        expected_version=2,
    )
    active = store.transition(
        active.id,
        expected=TaskState.PENDING,
        target=TaskState.READY,
        expected_version=0,
    )
    active = store.transition(
        active.id,
        expected=TaskState.READY,
        target=TaskState.RUNNING,
        expected_version=1,
    )
    with pytest.raises(InvalidTaskTransition):
        store.reset_for_rerun([completed.id, active.id])
    assert store.get(completed.id).state is TaskState.SUCCEEDED
    assert store.get(completed.id).cache_key == "a" * 64
    assert store.get(active.id).state is TaskState.RUNNING
