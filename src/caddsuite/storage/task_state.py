"""Transactional persistence for task states and their append-only transition history."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.domain.enums import TaskState
from caddsuite.storage.models import (
    TaskRow,
    TaskStateEventRow,
    utcnow,
)
from caddsuite.workflow.state import validate_transition


class TaskNotFound(LookupError):
    """The requested task does not exist."""


class TaskStateConflict(RuntimeError):
    """A compare-and-swap transition lost because another writer changed the state."""

    def __init__(
        self,
        task_id: str,
        expected: TaskState,
        actual: TaskState,
        expected_version: int,
        actual_version: int,
    ) -> None:
        self.task_id = task_id
        self.expected = expected
        self.actual = actual
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"task {task_id} is {actual.value!r} at version {actual_version}, "
            f"not expected {expected.value!r} at version {expected_version}"
        )


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    id: str
    run_id: str
    stage_id: str
    subject_kind: str | None
    subject_id: str | None
    state: TaskState
    version: int
    cache_key: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TaskTransition:
    id: str
    task_id: str
    from_state: TaskState | None
    to_state: TaskState
    version: int
    reason: str | None
    created_at: datetime


class TaskStateStore:
    """State changes use a SQL compare-and-swap and write history in one transaction."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create(
        self,
        *,
        run_id: str,
        stage_id: str,
        subject_kind: str | None = None,
        subject_id: str | None = None,
        cache_key: str | None = None,
    ) -> TaskSnapshot:
        if cache_key is not None and not re.fullmatch(r"[0-9a-f]{64}", cache_key):
            raise ValueError("cache_key must be a lowercase SHA-256 digest")
        with self._sessions.begin() as session:
            task = TaskRow(
                run_id=run_id,
                stage_id=stage_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                state=TaskState.PENDING.value,
                cache_key=cache_key,
            )
            session.add(task)
            session.flush()
            session.add(
                TaskStateEventRow(
                    task_id=task.id,
                    from_state=None,
                    version=0,
                    to_state=TaskState.PENDING.value,
                    reason="task created",
                )
            )
            session.flush()
            return _snapshot(task)

    def get(self, task_id: str) -> TaskSnapshot:
        with self._sessions() as session:
            task = session.get(TaskRow, task_id)
            if task is None:
                raise TaskNotFound(f"task {task_id!r} does not exist")
            return _snapshot(task)

    def transition(
        self,
        task_id: str,
        *,
        expected: TaskState,
        target: TaskState,
        expected_version: int,
        reason: str | None = None,
    ) -> TaskSnapshot:
        validate_transition(expected, target)
        if reason is not None and not reason.strip():
            raise ValueError("transition reason must not be blank")
        timestamp = utcnow()
        with self._sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.id == task_id,
                        TaskRow.state == expected.value,
                        TaskRow.version == expected_version,
                    )
                    .values(
                        state=target.value,
                        version=TaskRow.version + 1,
                        updated_at=timestamp,
                    )
                ),
            )
            if result.rowcount != 1:
                actual_row = session.execute(
                    select(TaskRow.state, TaskRow.version).where(TaskRow.id == task_id)
                ).one_or_none()
                if actual_row is None:
                    raise TaskNotFound(f"task {task_id!r} does not exist")
                actual_value, actual_version = actual_row
                try:
                    actual = TaskState(actual_value)
                except ValueError as exc:
                    raise RuntimeError(
                        f"task {task_id!r} has unknown persisted state {actual_value!r}"
                    ) from exc
                raise TaskStateConflict(task_id, expected, actual, expected_version, actual_version)

            session.add(
                TaskStateEventRow(
                    task_id=task_id,
                    version=expected_version + 1,
                    from_state=expected.value,
                    to_state=target.value,
                    reason=reason,
                    created_at=timestamp,
                )
            )
            task = session.get(TaskRow, task_id)
            if task is None:
                raise RuntimeError(f"updated task {task_id!r} disappeared in the same transaction")
            return _snapshot(task)

    def for_run(self, run_id: str) -> tuple[TaskSnapshot, ...]:
        with self._sessions() as session:
            tasks = session.scalars(
                select(TaskRow)
                .where(TaskRow.run_id == run_id)
                .order_by(TaskRow.stage_id, TaskRow.id)
            )
            return tuple(_snapshot(task) for task in tasks)

    def reset_for_rerun(
        self, task_ids: Sequence[str], *, reason: str = "user requested stage rerun"
    ) -> tuple[TaskSnapshot, ...]:
        # Active work must be cancelled and pending human decisions resolved first.
        unique_ids = tuple(dict.fromkeys(task_ids))
        if not unique_ids:
            raise ValueError("at least one task must be selected for rerun")
        if not reason.strip():
            raise ValueError("rerun reason must not be blank")
        timestamp = utcnow()
        with self._sessions.begin() as session:
            rows: list[TaskRow] = []
            for task_id in unique_ids:
                task = session.get(TaskRow, task_id)
                if task is None:
                    raise TaskNotFound(f"task {task_id!r} does not exist")
                rows.append(task)
            for task in rows:
                current = TaskState(task.state)
                if current is not TaskState.PENDING:
                    validate_transition(current, TaskState.PENDING)
            for task in rows:
                current = TaskState(task.state)
                if current is TaskState.PENDING:
                    continue
                version = task.version
                result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(TaskRow)
                        .where(
                            TaskRow.id == task.id,
                            TaskRow.state == current.value,
                            TaskRow.version == version,
                        )
                        .values(
                            state=TaskState.PENDING.value,
                            version=TaskRow.version + 1,
                            cache_key=None,
                            updated_at=timestamp,
                        )
                    ),
                )
                if result.rowcount != 1:
                    actual_row = session.execute(
                        select(TaskRow.state, TaskRow.version).where(TaskRow.id == task.id)
                    ).one()
                    actual_state = TaskState(actual_row[0])
                    raise TaskStateConflict(task.id, current, actual_state, version, actual_row[1])
                session.add(
                    TaskStateEventRow(
                        task_id=task.id,
                        version=version + 1,
                        from_state=current.value,
                        to_state=TaskState.PENDING.value,
                        reason=reason,
                        created_at=timestamp,
                    )
                )
            session.flush()
            refreshed = [session.get(TaskRow, task_id) for task_id in unique_ids]
            return tuple(_snapshot(task) for task in refreshed if task is not None)

    def history(self, task_id: str) -> tuple[TaskTransition, ...]:
        with self._sessions() as session:
            exists = session.scalar(select(TaskRow.id).where(TaskRow.id == task_id))
            if exists is None:
                raise TaskNotFound(f"task {task_id!r} does not exist")
            events: Sequence[TaskStateEventRow] = tuple(
                session.scalars(
                    select(TaskStateEventRow)
                    .where(TaskStateEventRow.task_id == task_id)
                    .order_by(TaskStateEventRow.version)
                )
            )
            return tuple(_transition(event) for event in events)


def _snapshot(task: TaskRow) -> TaskSnapshot:
    try:
        state = TaskState(task.state)
    except ValueError as exc:
        raise RuntimeError(f"task {task.id!r} has unknown persisted state {task.state!r}") from exc
    return TaskSnapshot(
        id=task.id,
        run_id=task.run_id,
        stage_id=task.stage_id,
        subject_kind=task.subject_kind,
        subject_id=task.subject_id,
        state=state,
        version=task.version,
        cache_key=task.cache_key,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _transition(event: TaskStateEventRow) -> TaskTransition:
    try:
        from_state = TaskState(event.from_state) if event.from_state is not None else None
        to_state = TaskState(event.to_state)
    except ValueError as exc:
        raise RuntimeError(f"task state event {event.id!r} contains an unknown state") from exc
    return TaskTransition(
        id=event.id,
        task_id=event.task_id,
        from_state=from_state,
        to_state=to_state,
        version=event.version,
        reason=event.reason,
        created_at=event.created_at,
    )
