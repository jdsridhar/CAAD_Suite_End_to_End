"""Transactional persistence primitives for local workflow worker ownership."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from time import monotonic
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.domain.enums import TaskState
from caddsuite.storage.models import (
    RunSubmissionRow,
    TaskRow,
    TaskStateEventRow,
    WorkflowRunRow,
)

logger = logging.getLogger(__name__)


def _rowcount(result: object) -> int:
    """Read the DB driver's affected-row count hidden by SQLAlchemy's broad Result type."""
    return int(cast(CursorResult[Any], result).rowcount or 0)


class RunSubmissionQueue:
    """Persist run payloads and guard claims with compare-and-swap updates."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def enqueue(self, run_id: str, payload: dict[str, Any]) -> None:
        with self._sessions.begin() as session:
            session.add(
                RunSubmissionRow(
                    run_id=run_id,
                    payload=payload,
                    state="queued",
                    submitted_at=datetime.now(UTC),
                )
            )

    def claim_next(
        self, worker_id: str, *, now: datetime | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        timestamp = now or datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.scalar(
                select(RunSubmissionRow)
                .where(RunSubmissionRow.state == "queued")
                .order_by(RunSubmissionRow.submitted_at, RunSubmissionRow.run_id)
                .limit(1)
            )
            if row is None:
                logger.debug(
                    "worker %s found no queued submission; states=%s",
                    worker_id,
                    session.scalars(select(RunSubmissionRow.state)).all(),
                )
                return None
            result = session.execute(
                update(RunSubmissionRow)
                .where(
                    RunSubmissionRow.run_id == row.run_id,
                    RunSubmissionRow.state == "queued",
                )
                .values(
                    state="running",
                    worker_id=worker_id,
                    heartbeat_at=timestamp,
                    started_at=timestamp,
                    error=None,
                )
            )
            if _rowcount(result) != 1:
                return None
            return row.run_id, dict(row.payload)

    def heartbeat(self, run_id: str, worker_id: str, *, now: datetime | None = None) -> bool:
        timestamp = now or datetime.now(UTC)
        with self._sessions.begin() as session:
            result = session.execute(
                update(RunSubmissionRow)
                .where(
                    RunSubmissionRow.run_id == run_id,
                    RunSubmissionRow.worker_id == worker_id,
                    RunSubmissionRow.state == "running",
                )
                .values(heartbeat_at=timestamp)
            )
            return _rowcount(result) == 1

    def finish(
        self,
        run_id: str,
        worker_id: str,
        *,
        state: str,
        error: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        if state not in {"succeeded", "failed", "stopped", "unknown", "awaiting_decision"}:
            raise ValueError(f"invalid terminal submission state {state!r}")
        timestamp = now or datetime.now(UTC)
        with self._sessions.begin() as session:
            result = session.execute(
                update(RunSubmissionRow)
                .where(
                    RunSubmissionRow.run_id == run_id,
                    RunSubmissionRow.worker_id == worker_id,
                    RunSubmissionRow.state == "running",
                )
                .values(
                    state=state,
                    finished_at=(None if state == "awaiting_decision" else timestamp),
                    heartbeat_at=timestamp,
                    error=error,
                )
            )
            if _rowcount(result) == 1:
                session.execute(
                    update(WorkflowRunRow)
                    .where(WorkflowRunRow.id == run_id)
                    .values(
                        status=state,
                        finished_at=(None if state == "awaiting_decision" else timestamp),
                    )
                )
            return _rowcount(result) == 1

    def request_cancel(self, run_id: str) -> bool:
        timestamp = datetime.now(UTC)
        with self._sessions.begin() as session:
            submission = session.get(RunSubmissionRow, run_id)
            if submission is None:
                return False
            if submission.state == "awaiting_decision":
                tasks = session.scalars(
                    select(TaskRow).where(
                        TaskRow.run_id == run_id,
                        TaskRow.state == TaskState.AWAITING_DECISION.value,
                    )
                ).all()
                for task in tasks:
                    result = session.execute(
                        update(TaskRow)
                        .where(
                            TaskRow.id == task.id,
                            TaskRow.state == TaskState.AWAITING_DECISION.value,
                            TaskRow.version == task.version,
                        )
                        .values(
                            state=TaskState.CANCELLED.value,
                            version=TaskRow.version + 1,
                            updated_at=timestamp,
                        )
                    )
                    if _rowcount(result) != 1:
                        raise RuntimeError(
                            f"task {task.id} changed while cancelling the paused workflow"
                        )
                    session.add(
                        TaskStateEventRow(
                            task_id=task.id,
                            version=task.version + 1,
                            from_state=TaskState.AWAITING_DECISION.value,
                            to_state=TaskState.CANCELLED.value,
                            reason="workflow run cancelled while awaiting decision",
                            created_at=timestamp,
                        )
                    )
                submission.state = "stopped"
                submission.cancel_requested = True
                submission.finished_at = timestamp
                submission.heartbeat_at = timestamp
                run = session.get(WorkflowRunRow, run_id)
                if run is not None:
                    run.status = "stopped"
                    run.finished_at = timestamp
                return True
            result = session.execute(
                update(RunSubmissionRow)
                .where(
                    RunSubmissionRow.run_id == run_id,
                    RunSubmissionRow.state.in_({"queued", "running"}),
                )
                .values(cancel_requested=True)
            )
            return _rowcount(result) == 1

    def cancellation_requested(self, run_id: str, worker_id: str) -> bool:
        with self._sessions() as session:
            row = session.get(RunSubmissionRow, run_id)
            return bool(
                row is not None
                and row.state == "running"
                and row.worker_id == worker_id
                and row.cancel_requested
            )

    def recover_expired(
        self,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> int:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        timestamp = now or datetime.now(UTC)
        cutoff = timestamp - timedelta(seconds=lease_seconds)
        with self._sessions.begin() as session:
            result = session.execute(
                update(RunSubmissionRow)
                .where(
                    RunSubmissionRow.state == "running",
                    RunSubmissionRow.heartbeat_at < cutoff,
                )
                .values(state="queued", worker_id=None, heartbeat_at=None)
            )
            return _rowcount(result)


class LocalRunSupervisor:
    """Poll the durable queue, renew ownership, and execute one local workflow at a time."""

    def __init__(
        self,
        queue: RunSubmissionQueue,
        execute: Callable[[str, dict[str, Any], Callable[[], bool]], str],
        *,
        worker_id: str,
        poll_seconds: float = 0.2,
        lease_seconds: int = 60,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if poll_seconds <= 0 or lease_seconds < 2:
            raise ValueError("poll_seconds must be positive and lease_seconds at least 2")
        self._queue = queue
        self._execute = execute
        self._worker_id = worker_id
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("run supervisor is already started")
        self._queue.recover_expired(lease_seconds=self._lease_seconds)
        self._thread = Thread(
            target=self._serve, name=f"caddsuite-worker-{self._worker_id}", daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float | None = None) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("run supervisor did not stop before timeout")
            self._thread = None

    def _serve(self) -> None:
        try:
            self._serve_queue()
        except Exception:
            logger.exception("local run supervisor %s stopped unexpectedly", self._worker_id)

    def _serve_queue(self) -> None:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="caddsuite-run") as pool:
            active: tuple[str, Future[str]] | None = None
            next_recovery = monotonic() + self._lease_seconds / 2
            while not self._stop.is_set() or active is not None:
                if monotonic() >= next_recovery:
                    self._queue.recover_expired(lease_seconds=self._lease_seconds)
                    next_recovery = monotonic() + self._lease_seconds / 2
                if active is None:
                    claimed = self._queue.claim_next(self._worker_id)
                    if claimed is not None:
                        run_id, payload = claimed

                        def cancellation_requested(run_id: str = run_id) -> bool:
                            return self._queue.cancellation_requested(run_id, self._worker_id)

                        future = pool.submit(self._execute, run_id, payload, cancellation_requested)
                        active = (run_id, future)
                        continue
                    self._stop.wait(self._poll_seconds)
                    continue

                run_id, future = active
                try:
                    terminal_state = future.result(timeout=self._poll_seconds)
                except TimeoutError:
                    self._queue.heartbeat(run_id, self._worker_id)
                    continue
                except Exception as exc:
                    logger.exception("workflow run %s failed in local supervisor", run_id)
                    self._queue.finish(
                        run_id,
                        self._worker_id,
                        state="failed",
                        error=f"{type(exc).__name__}: {exc}"[:2000],
                    )
                else:
                    self._queue.finish(run_id, self._worker_id, state=terminal_state)
                active = None
