from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.execution.local import CommandSpec, ExecutionError, LocalExecutor
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[tuple[LocalExecutor, Path]]:
    db_path = tmp_path / "execution.db"
    migrate.upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions: sessionmaker[Session] = make_session_factory(engine)
    yield LocalExecutor(ArtifactStore(tmp_path / "artifacts"), sessions), tmp_path / "logs"
    engine.dispose()


def test_argv_process_captures_logs_as_artifacts(
    executor: tuple[LocalExecutor, Path], tmp_path: Path
) -> None:
    local, log_dir = executor
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
    executor: tuple[LocalExecutor, Path], tmp_path: Path
) -> None:
    local, log_dir = executor
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


def test_invalid_argv_and_environment_are_rejected_before_spawn(
    executor: tuple[LocalExecutor, Path], tmp_path: Path
) -> None:
    local, log_dir = executor
    with pytest.raises(ValueError, match="argv"):
        local.start(CommandSpec(argv=(sys.executable, "\x00"), cwd=tmp_path), log_dir=log_dir)
    with pytest.raises(ValueError, match="environment variable name"):
        local.start(
            CommandSpec(argv=(sys.executable, "-V"), cwd=tmp_path, env={"BAD=KEY": "x"}),
            log_dir=log_dir,
        )
    with pytest.raises(ExecutionError, match="could not start"):
        local.start(CommandSpec(argv=("/no/such/executable",), cwd=tmp_path), log_dir=log_dir)
