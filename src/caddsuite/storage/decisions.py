from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.domain.enums import TaskState
from caddsuite.storage.models import (
    DecisionRow,
    RunSubmissionRow,
    TaskRow,
    TaskStateEventRow,
    ValidationIssueRow,
    WorkflowRunRow,
    utcnow,
)
from caddsuite.storage.task_state import TaskNotFound, TaskStateConflict
from caddsuite.validation.decisions import Decision, DecisionRequest
from caddsuite.workflow.state import validate_transition


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    decision_id: str
    issue_id: str
    task_id: str
    state: TaskState
    version: int
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionPause:
    issue_id: str
    task_id: str
    version: int


class DecisionStore:
    """Durably pause tasks on a request and atomically record a choice plus resume."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def await_decision(
        self, task_id: str, request: DecisionRequest, *, expected_version: int
    ) -> DecisionPause:
        current = TaskState.RUNNING
        target = TaskState.AWAITING_DECISION
        validate_transition(current, target)
        with self._sessions.begin() as session:
            task = session.get(TaskRow, task_id)
            if task is None:
                raise TaskNotFound(f"task {task_id!r} does not exist")
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
                ).one()
                actual = TaskState(row.state)
                raise TaskStateConflict(task_id, current, actual, expected_version, row.version)
            issue = ValidationIssueRow(
                code=request.issue_code,
                severity="decision_required",
                subject_kind=task.subject_kind or "task",
                subject_id=task.subject_id or task_id,
                message=request.question,
                payload=request.model_dump(mode="json"),
                task_id=task_id,
            )
            session.add(issue)
            session.add(
                TaskStateEventRow(
                    task_id=task_id,
                    version=expected_version + 1,
                    from_state=current.value,
                    to_state=target.value,
                    reason=f"decision required: {request.issue_code}",
                    created_at=utcnow(),
                )
            )
            session.flush()
            return DecisionPause(issue_id=issue.id, task_id=task_id, version=expected_version + 1)

    def submit(
        self,
        task_id: str,
        decision: Decision,
        *,
        expected_version: int,
        issue_id: str | None = None,
    ) -> DecisionOutcome:
        current = TaskState.AWAITING_DECISION
        target = TaskState.READY
        validate_transition(current, target)
        timestamp = decision.decided_at
        with self._sessions.begin() as session:
            task = session.get(TaskRow, task_id)
            if task is None:
                raise TaskNotFound(f"task {task_id!r} does not exist")
            if task.state != current.value or task.version != expected_version:
                actual = TaskState(task.state)
                raise TaskStateConflict(task_id, current, actual, expected_version, task.version)
            submission = session.get(RunSubmissionRow, task.run_id)
            if submission is not None and submission.state != "awaiting_decision":
                raise ValueError("workflow run is no longer awaiting this decision")
            pending_issues = session.scalars(
                select(ValidationIssueRow)
                .where(
                    ValidationIssueRow.task_id == task_id,
                    ValidationIssueRow.severity == "decision_required",
                )
                .order_by(ValidationIssueRow.created_at, ValidationIssueRow.id)
            ).all()
            issue = next(
                (
                    row
                    for row in pending_issues
                    if (issue_id is None or row.id == issue_id)
                    and session.scalar(select(DecisionRow.id).where(DecisionRow.issue_id == row.id))
                    is None
                ),
                None,
            )
            if issue is None:
                raise ValueError("no matching unresolved decision request exists for this task")
            persisted_request = DecisionRequest.model_validate(issue.payload)
            if persisted_request != decision.request:
                raise ValueError("submitted decision does not match the persisted request")
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
                actual = TaskState(row.state)
                raise TaskStateConflict(task_id, current, actual, expected_version, row.version)

            record = DecisionRow(
                issue_id=issue.id,
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
            if submission is not None and submission.state == "awaiting_decision":
                submission.state = "queued"
                submission.worker_id = None
                submission.heartbeat_at = None
                submission.finished_at = None
                submission.error = None
                run = session.get(WorkflowRunRow, task.run_id)
                if run is not None:
                    run.status = "queued"
                    run.finished_at = None
            session.flush()
            return DecisionOutcome(
                decision_id=record.id,
                issue_id=issue.id,
                task_id=task_id,
                state=target,
                version=expected_version + 1,
                decided_at=timestamp,
            )

    def for_task(self, task_id: str) -> tuple[Decision, ...]:
        with self._sessions() as session:
            payloads = session.scalars(
                select(DecisionRow.payload)
                .where(DecisionRow.task_id == task_id)
                .order_by(DecisionRow.decided_at, DecisionRow.id)
            ).all()
            return tuple(Decision.model_validate(payload) for payload in payloads)
