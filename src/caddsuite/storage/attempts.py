"""Persistence for versioned task-attempt provenance and PROV artifact/software edges."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.execution import (
    AttemptArtifact,
    AttemptStatus,
    ErrorRecord,
    StepRecord,
    TaskAttempt,
)
from caddsuite.domain.enums import TaskState
from caddsuite.storage.models import (
    ArtifactRow,
    AttemptAgentRow,
    AttemptArtifactRow,
    SoftwareAgentRow,
    SoftwareEnvironmentRow,
    TaskAttemptRow,
    TaskRow,
)


class AttemptNotFound(LookupError):
    """The requested task attempt does not exist."""


class AttemptConflict(RuntimeError):
    """An attempt is duplicated or has already reached a terminal state."""


class TaskAttemptStore:
    """Create an activity before launch, then atomically finalize status and output edges."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def next_attempt_no(self, task_id: str) -> int:
        with self._sessions() as session:
            if session.get(TaskRow, task_id) is None:
                raise LookupError(f"task {task_id!r} does not exist")
            latest = session.scalar(
                select(func.max(TaskAttemptRow.attempt_no)).where(TaskAttemptRow.task_id == task_id)
            )
            return 1 if latest is None else int(latest) + 1

    def begin(self, attempt: TaskAttempt) -> TaskAttempt:
        if attempt.status is not AttemptStatus.RUNNING:
            raise ValueError("new task attempts must begin in running state")
        if attempt.artifacts and any(item.direction != "used" for item in attempt.artifacts):
            raise ValueError(
                "only used/input artifact edges can be registered when an attempt begins"
            )
        with self._sessions.begin() as session:
            task = session.get(TaskRow, str(attempt.task_id))
            if task is None:
                raise LookupError(f"task {attempt.task_id!s} does not exist")
            if task.state != TaskState.RUNNING.value:
                raise AttemptConflict("task must be running before its attempt begins")
            latest_row = session.scalar(
                select(TaskAttemptRow)
                .where(TaskAttemptRow.task_id == str(attempt.task_id))
                .order_by(TaskAttemptRow.attempt_no.desc())
                .limit(1)
            )
            if latest_row is not None:
                if latest_row.exit_status == AttemptStatus.RUNNING.value:
                    raise AttemptConflict("task already has an unfinished execution attempt")
                if attempt.attempt_no != latest_row.attempt_no + 1:
                    raise AttemptConflict("attempt_no must follow the latest persisted attempt")
            elif attempt.attempt_no != 1:
                raise AttemptConflict("the first execution attempt must have attempt_no=1")
            existing = session.scalar(
                select(TaskAttemptRow.id).where(
                    TaskAttemptRow.task_id == str(attempt.task_id),
                    TaskAttemptRow.attempt_no == attempt.attempt_no,
                )
            )
            if existing is not None:
                raise AttemptConflict(
                    f"task {attempt.task_id!s} attempt {attempt.attempt_no} already exists"
                )
            attempt = self._persist_environment(session, attempt)
            row = TaskAttemptRow(
                id=str(attempt.id),
                task_id=str(attempt.task_id),
                attempt_no=attempt.attempt_no,
                executor=attempt.executor,
                environment_id=(
                    str(attempt.environment.id) if attempt.environment is not None else None
                ),
                host=attempt.host.model_dump(mode="json"),
                resources=attempt.resources.model_dump(mode="json") if attempt.resources else None,
                steps=[],
                platform=attempt.platform.model_dump(mode="json"),
                payload=attempt.model_dump(mode="json"),
                started_at=attempt.started_at,
                ended_at=None,
                exit_status=AttemptStatus.RUNNING.value,
                error=None,
            )
            session.add(row)
            session.flush()
            self._persist_agents(session, attempt)
            self._persist_edges(session, attempt.id, attempt.artifacts)
            return attempt

    def finish(
        self,
        attempt_id: str,
        *,
        status: AttemptStatus,
        ended_at: datetime,
        steps: Iterable[StepRecord],
        error: ErrorRecord | None = None,
        generated_artifacts: Iterable[AttemptArtifact] = (),
    ) -> TaskAttempt:
        if status is AttemptStatus.RUNNING:
            raise ValueError("finish status must be terminal")
        step_payloads = [self._step_payload(step) for step in steps]
        generated = tuple(generated_artifacts)
        if any(item.direction != "generated" for item in generated):
            raise ValueError("finish accepts generated/output artifact edges only")
        with self._sessions.begin() as session:
            row = session.get(TaskAttemptRow, attempt_id)
            if row is None:
                raise AttemptNotFound(f"task attempt {attempt_id!r} does not exist")
            if row.payload is None:
                raise RuntimeError("persisted task attempt has no versioned provenance payload")
            previous = TaskAttempt.model_validate(row.payload)
            if previous.status is not AttemptStatus.RUNNING:
                raise AttemptConflict(f"task attempt {attempt_id!r} is already terminal")
            payload = previous.model_dump(mode="python")
            payload.update(
                {
                    "status": status.value,
                    "ended_at": ended_at,
                    "steps": step_payloads,
                    "error": error.model_dump(mode="python") if error is not None else None,
                    "artifacts": [
                        *payload["artifacts"],
                        *(edge.model_dump(mode="python") for edge in generated),
                    ],
                }
            )
            completed = TaskAttempt.model_validate(payload)
            row.steps = [step.model_dump(mode="json") for step in completed.steps]
            row.ended_at = completed.ended_at
            row.exit_status = completed.status.value
            row.error = completed.error.model_dump(mode="json") if completed.error else None
            row.payload = completed.model_dump(mode="json")
            self._persist_edges(session, completed.id, generated)
            return completed

    def running_for_task(self, task_id: str) -> TaskAttempt | None:
        """Return the sole open attempt for resume reconciliation, if one exists."""
        with self._sessions() as session:
            rows = session.scalars(
                select(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == task_id,
                    TaskAttemptRow.exit_status == AttemptStatus.RUNNING.value,
                )
                .order_by(TaskAttemptRow.attempt_no.desc())
            ).all()
            if len(rows) > 1:
                raise AttemptConflict(f"task {task_id!r} has multiple unfinished attempts")
            if not rows:
                return None
            if rows[0].payload is None:
                raise RuntimeError("persisted task attempt has no versioned provenance payload")
            return TaskAttempt.model_validate(rows[0].payload)

    def get(self, attempt_id: str) -> TaskAttempt:
        with self._sessions() as session:
            row = session.get(TaskAttemptRow, attempt_id)
            if row is None:
                raise AttemptNotFound(f"task attempt {attempt_id!r} does not exist")
            if row.payload is None:
                raise RuntimeError("persisted task attempt has no versioned provenance payload")
            return TaskAttempt.model_validate(row.payload)

    @staticmethod
    def _step_payload(step: StepRecord) -> dict[str, object]:
        return step.model_dump(mode="python")

    @staticmethod
    def _persist_environment(session: Session, attempt: TaskAttempt) -> TaskAttempt:
        environment = attempt.environment
        if environment is None:
            return attempt
        if environment.lock is not None:
            lock_artifact = session.get(ArtifactRow, str(environment.lock.artifact_id))
            if lock_artifact is None:
                raise ValueError("environment lock artifact is not registered")
            if (
                environment.lock.sha256 is not None
                and environment.lock.sha256 != lock_artifact.sha256
            ):
                raise ValueError("environment lock artifact hash does not match registered bytes")
        row = session.get(SoftwareEnvironmentRow, str(environment.id))
        if row is None:
            row = session.scalar(
                select(SoftwareEnvironmentRow).where(
                    SoftwareEnvironmentRow.prefix == environment.prefix,
                    SoftwareEnvironmentRow.lock_sha256 == environment.lock_sha256,
                )
            )
        if row is None:
            row = SoftwareEnvironmentRow(
                id=str(environment.id),
                kind=environment.kind.value,
                name=environment.name,
                prefix=environment.prefix,
                lock_sha256=environment.lock_sha256,
                lock_artifact_id=(
                    str(environment.lock.artifact_id) if environment.lock is not None else None
                ),
                key_packages=dict(environment.key_packages),
                captured_at=environment.captured_at,
            )
            session.add(row)
            session.flush()
            return attempt
        if row.lock_sha256 != environment.lock_sha256 or row.prefix != environment.prefix:
            raise ValueError("software environment identity conflicts with an existing record")
        if str(environment.id) == row.id:
            return attempt
        value = attempt.model_dump(mode="python")
        value["environment"] = {**value["environment"], "id": row.id}
        return TaskAttempt.model_validate(value)

    @staticmethod
    def _persist_agents(session: Session, attempt: TaskAttempt) -> None:
        for association in attempt.software:
            software = association.software
            kind = software.kind.value
            agent = session.scalar(
                select(SoftwareAgentRow).where(
                    SoftwareAgentRow.name == software.name,
                    SoftwareAgentRow.version == software.version,
                    SoftwareAgentRow.kind == kind,
                )
            )
            if agent is None:
                agent = SoftwareAgentRow(
                    name=software.name,
                    version=software.version,
                    kind=kind,
                    license_class=software.license_class.value,
                )
                session.add(agent)
                session.flush()
            if len(association.role) > 32:
                raise ValueError("software agent role must be at most 32 characters")
            session.add(
                AttemptAgentRow(
                    attempt_id=str(attempt.id), agent_id=agent.id, role=association.role
                )
            )

    @staticmethod
    def _persist_edges(session: Session, attempt_id: str, edges: Iterable[AttemptArtifact]) -> None:
        for edge in edges:
            if len(edge.role) > 64:
                raise ValueError("artifact edge role must be at most 64 characters")
            artifact_id = str(edge.artifact.artifact_id)
            artifact = session.get(ArtifactRow, artifact_id)
            if artifact is None:
                raise ValueError(f"artifact {artifact_id!r} is not registered")
            if edge.artifact.sha256 is not None and edge.artifact.sha256 != artifact.sha256:
                raise ValueError(
                    f"artifact {artifact_id!r} hash differs from the registered artifact"
                )
            if edge.direction == "generated" and artifact.producer_attempt_id is None:
                artifact.producer_attempt_id = attempt_id
            session.add(
                AttemptArtifactRow(
                    attempt_id=attempt_id,
                    artifact_id=artifact_id,
                    direction=edge.direction,
                    role=edge.role,
                )
            )
