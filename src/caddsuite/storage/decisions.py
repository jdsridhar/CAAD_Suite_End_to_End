"""Atomic human-decision persistence and workflow resumption."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.domain.enums import TaskState
from caddsuite.storage.models import DecisionRow, TaskRow, TaskStateEventRow, utcnow
from caddsuite.storage.task_state import TaskNotFound, TaskStateConflict
from caddsuite.validation.decisions import Decision
from caddsuite.workflow.state import validate_transition


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    decision_id: str
    task_id: str
    state: TaskState
    version: int
    decided_at: datetime


class DecisionStore:
    """Record the decision, transition, and state-history edge in one DB transaction."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def submit(self, task_id: str, decision: Decision, *, expected_version: int) -> DecisionOutcome:
        current = TaskState.AWAITING_DECISION
        target = TaskState.READY
        validate_transition(current, target)
        timestamp = decision.decided_at
        with self._sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.id == task_id,
                        TaskRow.state == current.value,
                        TaskRow.version == expected_version,
                    )
                    .values(
                        state=target.value,
                        version=TaskRow.version + 1,
                        updated_at=utcnow(),
                    )
                ),
            )
            if result.rowcount != 1:
                row = session.execute(
                    select(TaskRow.state, TaskRow.version).where(TaskRow.id == task_id)
                ).one_or_none()
                if row is None:
                    raise TaskNotFound(f"task {task_id!r} does not exist")
                state_value, version = row
                try:
                    actual = TaskState(state_value)
                except ValueError as exc:
                    raise RuntimeError(
                        f"task {task_id!r} has unknown persisted state {state_value!r}"
                    ) from exc
                raise TaskStateConflict(task_id, current, actual, expected_version, version)

            record = DecisionRow(
                task_id=task_id,
                chosen_key=decision.chosen_key,
                decided_by=decision.decided_by,
                decided_at=timestamp,
                scope=decision.scope.value,
                payload=decision.model_dump(mode="json"),
            )
            session.add(record)
            session.add(
                TaskStateEventRow(
                    task_id=task_id,
                    version=expected_version + 1,
                    from_state=current.value,
                    to_state=target.value,
                    reason=f"decision selected: {decision.chosen_key}",
                    created_at=utcnow(),
                )
            )
            session.flush()
            return DecisionOutcome(
                decision_id=record.id,
                task_id=task_id,
                state=target,
                version=expected_version + 1,
                decided_at=timestamp,
            )
