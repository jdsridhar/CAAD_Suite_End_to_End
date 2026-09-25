from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from caddsuite.application.run_queue import LocalRunSupervisor, RunSubmissionQueue
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import ProjectRow, RunSubmissionRow, WorkflowRunRow


def _queue(tmp_path: Path) -> tuple[RunSubmissionQueue, object, str]:
    db_path = tmp_path / "caddsuite.sqlite"
    upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    with sessions.begin() as session:
        project = ProjectRow(slug="run-queue", name="Run queue")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-QUEUE-001",
            workflow_hash="a" * 64,
            config_hash="b" * 64,
            status="queued",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    return RunSubmissionQueue(sessions), (engine, sessions), run_id


def test_submission_is_persisted_and_claimed_once(tmp_path: Path) -> None:
    queue, (_engine, sessions), run_id = _queue(tmp_path)
    queue.enqueue(run_id, {"workflow": {"schema": "workflow/1"}, "inputs": {}})

    first = queue.claim_next("worker-one")
    second = queue.claim_next("worker-two")

    assert first == (run_id, {"workflow": {"schema": "workflow/1"}, "inputs": {}})
    assert second is None
    with sessions() as session:
        row = session.get(RunSubmissionRow, run_id)
        assert row is not None
        assert row.state == "running"
        assert row.worker_id == "worker-one"


def test_expired_worker_lease_requeues_submission(tmp_path: Path) -> None:
    queue, (_engine, _sessions), run_id = _queue(tmp_path)
    now = datetime.now(UTC)
    queue.enqueue(run_id, {"workflow": {}, "inputs": {}})
    assert queue.claim_next("worker-one", now=now) is not None
    assert queue.recover_expired(lease_seconds=20, now=now + timedelta(seconds=21)) == 1

    claimed = queue.claim_next("worker-two", now=now + timedelta(seconds=22))
    assert claimed is not None
    assert claimed[0] == run_id


def test_local_supervisor_executes_and_persists_terminal_state(tmp_path: Path) -> None:
    queue, (engine, sessions), run_id = _queue(tmp_path)
    queue.enqueue(run_id, {"inputs": {}})
    finished = Event()

    def execute(_run_id: str, _payload: dict[str, object], cancelled: object) -> str:
        assert callable(cancelled)
        finished.set()
        return "succeeded"

    supervisor = LocalRunSupervisor(
        queue, execute, worker_id="test-worker", poll_seconds=0.01, lease_seconds=10
    )
    supervisor.start()
    deadline = monotonic() + 3
    while not finished.is_set() and monotonic() < deadline:
        sleep(0.01)
    supervisor.stop(timeout=3)

    with sessions() as session:
        row = session.get(RunSubmissionRow, run_id)
        assert row is not None
        assert row.state == "succeeded"
    engine.dispose()


def test_cancel_request_is_visible_to_the_owning_worker(tmp_path: Path) -> None:
    queue, (_engine, _sessions), run_id = _queue(tmp_path)
    queue.enqueue(run_id, {"inputs": {}})
    assert queue.claim_next("worker-one") is not None

    assert queue.request_cancel(run_id)
    assert queue.cancellation_requested(run_id, "worker-one")
    assert not queue.cancellation_requested(run_id, "worker-two")


def test_supervisor_startup_recovers_expired_worker_lease(tmp_path: Path) -> None:
    queue, (engine, sessions), run_id = _queue(tmp_path)
    now = datetime.now(UTC)
    queue.enqueue(run_id, {"inputs": {}})
    assert queue.claim_next("crashed-worker", now=now - timedelta(seconds=120)) is not None
    recovered = Event()

    def execute(_run_id: str, _payload: dict[str, object], _cancelled: object) -> str:
        recovered.set()
        return "succeeded"

    supervisor = LocalRunSupervisor(
        queue, execute, worker_id="replacement-worker", poll_seconds=0.01, lease_seconds=60
    )
    supervisor.start()
    try:
        assert recovered.wait(timeout=3)
    finally:
        supervisor.stop(timeout=3)

    with sessions() as session:
        row = session.get(RunSubmissionRow, run_id)
        run = session.get(WorkflowRunRow, run_id)
        assert row is not None
        assert row.state == "succeeded"
        assert run is not None
        assert run.status == "succeeded"
    engine.dispose()
