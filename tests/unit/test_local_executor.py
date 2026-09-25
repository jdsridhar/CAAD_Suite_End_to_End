from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from threading import Event, Timer

import pytest
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.domain.enums import TaskState
from caddsuite.domain.errors import ExecutionCancelled
from caddsuite.execution.local import CommandSpec, ExecutionError, LocalExecutor, ProcessRecord
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ProjectRow, WorkflowRunRow
from caddsuite.storage.task_state import TaskStateStore


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[tuple[LocalExecutor, Path, sessionmaker[Session]]]:
    db_path = tmp_path / "execution.db"
    migrate.upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions: sessionmaker[Session] = make_session_factory(engine)
    yield (
        LocalExecutor(ArtifactStore(tmp_path / "artifacts"), sessions),
        tmp_path / "logs",
        sessions,
    )
    engine.dispose()


def test_argv_process_captures_logs_as_artifacts(
    executor: tuple[LocalExecutor, Path, sessionmaker[Session]], tmp_path: Path
) -> None:
    local, log_dir, _sessions = executor
    command = local.start(
        CommandSpec(
            argv=(
                sys.executable,
                "-c",
                "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)",
            ),
            cwd=tmp_path,
        ),
        log_dir=log_dir,
    )
    assert command.record.pid > 0
    result = command.wait(timeout=10)
    assert result.exit_code == 7
    assert result.step.exit_code == 7
    assert result.duration_seconds >= 0
    assert local._artifacts.open(result.stdout.sha256).read() == b"out\n"
    assert local._artifacts.open(result.stderr.sha256).read() == b"err\n"


def test_reattach_and_cancel_kills_the_process_group(
    executor: tuple[LocalExecutor, Path, sessionmaker[Session]], tmp_path: Path
) -> None:
    local, log_dir, _sessions = executor
    command = local.start(
        CommandSpec(argv=(sys.executable, "-c", "import time; time.sleep(30)"), cwd=tmp_path),
        log_dir=log_dir,
    )
    attached = local.reattach(command.record)
    assert attached.record == command.record
    assert attached.poll() is None
    attached.cancel(grace_seconds=0.2)
    result = command.wait(timeout=5)
    assert result.exit_code != 0


def test_cancellation_terminates_child_processes_in_the_group(
    executor: tuple[LocalExecutor, Path, sessionmaker[Session]], tmp_path: Path
) -> None:
    local, log_dir, _sessions = executor
    child_pid_file = tmp_path / "grandchild.pid"
    parent_code = (
        "import subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"open({str(child_pid_file)!r}, 'w').write(str(child.pid)); "
        "time.sleep(60)"
    )
    command = local.start(
        CommandSpec(argv=(sys.executable, "-c", parent_code), cwd=tmp_path),
        log_dir=log_dir,
    )
    deadline = time.monotonic() + 10
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child_pid_file.exists(), "parent did not start its child process"
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    command.cancel(grace_seconds=0.5)
    command.wait(timeout=5)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        stat_path = Path(f"/proc/{child_pid}/stat")
        if not stat_path.exists():
            break
        stat_text = stat_path.read_text(encoding="utf-8")
        close = stat_text.rfind(")")
        if close >= 0 and stat_text[close + 2 :].split()[0] in {"Z", "X"}:
            break
        time.sleep(0.05)
    stat_path = Path(f"/proc/{child_pid}/stat")
    if stat_path.exists():
        stat_text = stat_path.read_text(encoding="utf-8")
        close = stat_text.rfind(")")
        assert close >= 0
        state = stat_text[close + 2 :].split()[0]
        assert state in {"Z", "X"}


def test_killed_supervisor_can_reattach_and_resume_the_task(
    executor: tuple[LocalExecutor, Path, sessionmaker[Session]], tmp_path: Path
) -> None:
    local, log_dir, sessions = executor
    with sessions.begin() as session:
        project = ProjectRow(slug="resume-test", name="Resume test")
        session.add(project)
        session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession="RUN-20260924-005",
            workflow_hash="f" * 64,
            config_hash="e" * 64,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    state_store = TaskStateStore(sessions)
    task = state_store.create(run_id=run_id, stage_id="long_step")
    task = state_store.transition(
        task.id, expected=TaskState.PENDING, target=TaskState.READY, expected_version=0
    )
    task = state_store.transition(
        task.id, expected=TaskState.READY, target=TaskState.RUNNING, expected_version=1
    )

    record_path = tmp_path / "process-record.json"
    worker_script = tmp_path / "worker.py"
    worker_script.write_text(
        "import json, sys, time\n"
        "from dataclasses import asdict\n"
        "from datetime import datetime\n"
        "from pathlib import Path\n"
        "from caddsuite.execution.local import CommandSpec, LocalExecutor\n"
        "from caddsuite.storage.artifacts import ArtifactStore\n"
        "from caddsuite.storage.db import create_db_engine, make_session_factory\n"
        "db, artifacts, work, output = map(Path, sys.argv[1:])\n"
        "engine = create_db_engine(db)\n"
        "executor = LocalExecutor(ArtifactStore(artifacts), make_session_factory(engine))\n"
        "running = executor.start(CommandSpec((sys.executable, '-c', "
        "'import time; time.sleep(60)'), work), log_dir=work)\n"
        "data = asdict(running.record)\n"
        "data['started_at'] = running.record.started_at.isoformat()\n"
        "Path(output).write_text(json.dumps(data))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    worker = subprocess.Popen(
        [
            sys.executable,
            str(worker_script),
            str(tmp_path / "execution.db"),
            str(local._artifacts.root),
            str(tmp_path),
            str(record_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        shell=False,
    )
    deadline = time.monotonic() + 10
    while not record_path.exists() and time.monotonic() < deadline:
        if worker.poll() is not None:
            stderr = worker.stderr.read().decode(errors="replace") if worker.stderr else ""
            pytest.fail(f"executor worker exited early: {stderr}")
        time.sleep(0.05)
    assert record_path.exists(), "worker did not publish the process locator"
    os.kill(worker.pid, signal.SIGKILL)
    worker.wait(timeout=5)

    data = json.loads(record_path.read_text(encoding="utf-8"))
    data["argv"] = tuple(data["argv"])
    data["started_at"] = datetime.fromisoformat(data["started_at"])
    record = ProcessRecord(**data)
    interrupted = state_store.transition(
        task.id,
        expected=TaskState.RUNNING,
        target=TaskState.INTERRUPTED,
        expected_version=task.version,
        reason="supervisor was killed",
    )

    attached = local.reattach(record)
    assert attached.poll() is None
    attached.cancel(grace_seconds=0.2)
    resumed = state_store.transition(
        task.id,
        expected=TaskState.INTERRUPTED,
        target=TaskState.READY,
        expected_version=interrupted.version,
        reason="reattached old process was stopped; retrying",
    )
    resumed = state_store.transition(
        task.id,
        expected=TaskState.READY,
        target=TaskState.RUNNING,
        expected_version=resumed.version,
    )
    retry = local.start(
        CommandSpec((sys.executable, "-c", "print('resumed')"), tmp_path),
        log_dir=log_dir,
    )
    result = retry.wait(timeout=10)
    final = state_store.transition(
        task.id,
        expected=TaskState.RUNNING,
        target=TaskState.SUCCEEDED,
        expected_version=resumed.version,
    )
    assert final.state is TaskState.SUCCEEDED
    assert result.exit_code == 0


def test_invalid_argv_and_environment_are_rejected_before_spawn(
    executor: tuple[LocalExecutor, Path, sessionmaker[Session]], tmp_path: Path
) -> None:
    local, log_dir, _sessions = executor
    with pytest.raises(ValueError, match="argv"):
        local.start(CommandSpec(argv=(sys.executable, "\x00"), cwd=tmp_path), log_dir=log_dir)
    with pytest.raises(ValueError, match="environment variable name"):
        local.start(
            CommandSpec(argv=(sys.executable, "-V"), cwd=tmp_path, env={"BAD=KEY": "x"}),
            log_dir=log_dir,
        )
    with pytest.raises(ExecutionError, match="could not start"):
        local.start(CommandSpec(argv=("/no/such/executable",), cwd=tmp_path), log_dir=log_dir)


def test_step_record_captures_explicit_environment_and_redacts_secrets(
    executor: tuple[LocalExecutor, Path, sessionmaker[Session]], tmp_path: Path
) -> None:
    local, log_dir, _sessions = executor
    command = local.start(
        CommandSpec(
            argv=(sys.executable, "-c", "pass"),
            cwd=tmp_path,
            env={
                "OMP_NUM_THREADS": "2",
                "CONDA_PREFIX": "/envs/science",
                "API_TOKEN": "never-persist-this",
                "GPG_KEY": "never-persist-this-either",
            },
        ),
        log_dir=log_dir,
    )
    result = command.wait(timeout=10)
    assert result.step.env_subset == {
        "API_TOKEN": "[REDACTED]",
        "CONDA_PREFIX": "/envs/science",
        "GPG_KEY": "[REDACTED]",
        "OMP_NUM_THREADS": "2",
    }
    assert "never-persist-this" not in repr(result.step.model_dump())


def test_cancellation_callback_kills_process_and_captures_logs(
    tmp_path: Path, executor: tuple[LocalExecutor, Path, sessionmaker[Session]]
) -> None:
    _base, log_dir, sessions = executor
    cancellation = Event()
    local = LocalExecutor(
        ArtifactStore(tmp_path / "cancel-artifacts"),
        sessions,
        cancellation_check=cancellation.is_set,
    )
    command = local.start(
        CommandSpec(argv=(sys.executable, "-c", "import time; time.sleep(30)"), cwd=tmp_path),
        log_dir=log_dir,
    )
    timer = Timer(0.15, cancellation.set)
    timer.start()
    try:
        with pytest.raises(ExecutionCancelled, match="process-group termination"):
            command.wait(timeout=5)
    finally:
        timer.cancel()
        timer.join(timeout=1)

    assert command.poll() is not None
    assert command._result is not None
    assert command._result.exit_code != 0
    assert local._artifacts.open(command._result.stderr.sha256).read() == b""
