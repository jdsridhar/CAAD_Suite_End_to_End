"""Safe local argv execution with process-group control and content-addressed logs.

The scientific adapter supplies a plan; this module owns process mechanics only.
It has no knowledge of docking, MD, QM, or any particular engine.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.execution import StepRecord
from caddsuite.domain.errors import ExecutionCancelled
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob

_ENV_KEY = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_SECRET_ENV_KEY = re.compile(
    r"(?:PASS(?:WORD)?|TOKEN|SECRET|CREDENTIAL|AUTH|COOKIE|PRIVATE|KEY)", re.IGNORECASE
)
_REDACTED = "[REDACTED]"


def _provenance_environment(values: Mapping[str, str]) -> dict[str, str]:
    """Capture explicit environment overrides while redacting credential-like variables."""
    return {
        key: _REDACTED if _SECRET_ENV_KEY.search(key) else value
        for key, value in sorted(values.items())
    }


class ExecutionError(RuntimeError):
    """A process could not be safely started, reattached, or finalized."""


@dataclass(frozen=True, slots=True)
class CommandSpec:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ProcessRecord:
    """Serializable locator needed to reattach after the parent application restarts."""

    argv: tuple[str, ...]
    cwd: str
    pid: int
    process_start_time: float
    started_at: datetime
    stdout_path: str
    stderr_path: str
    env_subset: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    step: StepRecord
    exit_code: int
    duration_seconds: float
    stdout: ArtifactRef
    stderr: ArtifactRef


class RunningCommand:
    def __init__(
        self,
        executor: LocalExecutor,
        record: ProcessRecord,
        process: subprocess.Popen[bytes] | None,
        started_monotonic: float | None,
    ) -> None:
        self.record = record
        self._executor = executor
        self._process = process
        self._started_monotonic = started_monotonic
        self._result: ExecutionResult | None = None

    def poll(self) -> int | None:
        if self._process is not None:
            return self._process.poll()
        if _same_process_is_alive(self.record):
            return None
        raise ExecutionError(
            "reattached process ended; its exit code is unavailable after the original"
            " supervisor exited"
        )

    def wait(self, timeout: float | None = None) -> ExecutionResult:
        if self._result is not None:
            return self._result
        cancellation_confirmed = False
        if self._executor.cancellation_check is None:
            if self._process is not None:
                exit_code = self._process.wait(timeout=timeout)
            else:
                deadline = None if timeout is None else time.monotonic() + timeout
                while _same_process_is_alive(self.record):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(
                            self.record.argv, timeout if timeout is not None else 0
                        )
                    time.sleep(0.1)
                raise ExecutionError(
                    "reattached process ended without an exit status; its outcome is unknown"
                )
        else:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                if self._process is not None:
                    polled_exit_code = self._process.poll()
                    if polled_exit_code is not None:
                        exit_code = polled_exit_code
                        break
                elif not _same_process_is_alive(self.record):
                    raise ExecutionError(
                        "reattached process ended without an exit status; its outcome is unknown"
                    )
                if self._executor.cancellation_check():
                    self.cancel()
                    cancellation_confirmed = True
                    cancelled_exit_code = (
                        self._process.returncode if self._process is not None else -signal.SIGTERM
                    )
                    if cancelled_exit_code is None:
                        raise ExecutionError(
                            "cancellation was requested but process exit is unknown"
                        )
                    exit_code = cancelled_exit_code
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(
                        self.record.argv, timeout if timeout is not None else 0
                    )
                time.sleep(0.2)
        self._result = self._executor._finalize(
            self.record,
            exit_code,
            self._elapsed(),
        )
        if cancellation_confirmed:
            raise ExecutionCancelled(
                f"cancelled process {self.record.pid} after process-group termination"
            )
        return self._result

    def cancel(self, *, grace_seconds: float = 5.0) -> None:
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be non-negative")
        if not _same_process_is_alive(self.record):
            return
        try:
            os.killpg(self.record.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + grace_seconds
        while _same_process_is_alive(self.record) and time.monotonic() < deadline:
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        if _same_process_is_alive(self.record):
            with suppress(ProcessLookupError):
                os.killpg(self.record.pid, signal.SIGKILL)
        if self._process is not None:
            self._process.wait()

    def _elapsed(self) -> float:
        if self._started_monotonic is not None:
            return max(0.0, time.monotonic() - self._started_monotonic)
        return max(0.0, (datetime.now(UTC) - self.record.started_at).total_seconds())


class LocalExecutor:
    """Run argv commands in isolated POSIX process groups and store their logs as artifacts."""

    def __init__(
        self,
        artifacts: ArtifactStore,
        sessions: sessionmaker[Session],
        *,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> None:
        if os.name != "posix" or not Path("/proc").is_dir():
            raise RuntimeError("LocalExecutor currently requires a Linux /proc environment")
        self._artifacts = artifacts
        self._sessions = sessions
        self.cancellation_check = cancellation_check

    def start(self, spec: CommandSpec, *, log_dir: Path) -> RunningCommand:
        argv, cwd, env = _validate_spec(spec)
        log_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"task-{new_ulid()}"
        stdout_path = log_dir / f"{prefix}.stdout.log"
        stderr_path = log_dir / f"{prefix}.stderr.log"
        stdout: IO[bytes] | None = None
        stderr: IO[bytes] | None = None
        try:
            stdout = stdout_path.open("xb")
            stderr = stderr_path.open("xb")
            process = subprocess.Popen(  # noqa: S603 - argv-only, shell=False, validated cwd/env
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                close_fds=True,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            for stream in (stdout, stderr):
                if stream is not None:
                    stream.close()
            raise ExecutionError(f"could not start process {argv[0]!r}: {exc}") from exc
        else:
            stdout.close()
            stderr.close()

        started_at = datetime.now(UTC)
        start_time = _proc_start_time(process.pid)
        if start_time is None:
            process.kill()
            process.wait()
            raise ExecutionError("started process exited before its identity could be recorded")
        record = ProcessRecord(
            argv=argv,
            cwd=str(cwd),
            pid=process.pid,
            process_start_time=start_time,
            started_at=started_at,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            env_subset=_provenance_environment(spec.env or {}),
        )
        return RunningCommand(self, record, process, time.monotonic())

    def reattach(self, record: ProcessRecord) -> RunningCommand:
        if not _same_process_is_alive(record):
            raise ExecutionError(
                f"PID {record.pid} is no longer the recorded process (it exited or was reused)"
            )
        for path in (Path(record.stdout_path), Path(record.stderr_path)):
            if not path.is_file():
                raise ExecutionError(f"process log is missing: {path}")
        return RunningCommand(self, record, None, None)

    def _finalize(
        self, record: ProcessRecord, exit_code: int, duration_seconds: float
    ) -> ExecutionResult:
        stdout_blob = self._artifacts.put_file(Path(record.stdout_path))
        stderr_blob = self._artifacts.put_file(Path(record.stderr_path))
        with self._sessions.begin() as session:
            stdout_row = register_blob(
                session,
                stdout_blob,
                kind="execution_stdout",
                media_type="text/plain",
                original_name=Path(record.stdout_path).name,
            )
            stderr_row = register_blob(
                session,
                stderr_blob,
                kind="execution_stderr",
                media_type="text/plain",
                original_name=Path(record.stderr_path).name,
            )
            stdout_id, stderr_id = stdout_row.id, stderr_row.id
        result = ExecutionResult(
            step=StepRecord(
                argv=record.argv,
                cwd=record.cwd,
                pid=record.pid,
                process_start_time=record.process_start_time,
                exit_code=exit_code,
                env_subset=dict(record.env_subset),
            ),
            exit_code=exit_code,
            duration_seconds=duration_seconds,
            stdout=ArtifactRef(
                artifact_id=stdout_id,
                role="stdout",
                sha256=stdout_blob.sha256,
            ),
            stderr=ArtifactRef(
                artifact_id=stderr_id,
                role="stderr",
                sha256=stderr_blob.sha256,
            ),
        )
        from caddsuite.execution.attempt_context import record_process_execution

        record_process_execution(result.step, result.stdout, result.stderr)
        return result


def _validate_spec(spec: CommandSpec) -> tuple[tuple[str, ...], Path, dict[str, str]]:
    if not spec.argv or any(not arg or "\x00" in arg for arg in spec.argv):
        raise ValueError("argv must contain non-empty strings without NUL bytes")
    cwd = spec.cwd.expanduser().resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError(f"working directory is not a directory: {cwd}")
    env = os.environ.copy()
    if spec.env is not None:
        for key, value in spec.env.items():
            if not key or any(char not in _ENV_KEY for char in key) or "=" in key:
                raise ValueError(f"invalid environment variable name: {key!r}")
            if "\x00" in value:
                raise ValueError(f"environment variable {key!r} contains a NUL byte")
            env[key] = value
    return spec.argv, cwd, env


def _proc_start_time(pid: int) -> float | None:
    state, start_time = _proc_identity(pid)
    return start_time if state is not None else None


def _proc_identity(pid: int) -> tuple[str | None, float | None]:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None, None
    close = stat.rfind(")")
    if close < 0:
        return None, None
    fields = stat[close + 2 :].split()
    try:
        return fields[0], float(fields[19])
    except (IndexError, ValueError):
        return None, None


def _same_process_is_alive(record: ProcessRecord) -> bool:
    state, start_time = _proc_identity(record.pid)
    return state is not None and state not in {"Z", "X"} and start_time == record.process_start_time
