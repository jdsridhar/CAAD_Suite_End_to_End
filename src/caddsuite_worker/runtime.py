"""Python-standard-library JSON runtime for isolated scientific workers.

Workers exchange a versioned task envelope, append structured JSONL events, and
write one normalized result envelope. Engine-specific validation stays in each
worker; this module only defines the process boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, TextIO

from caddsuite_worker import PROTOCOL_VERSION

_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPERATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVENT_TYPES = {"log", "progress", "warning"}


class WorkerFailure(Exception):
    """Expected, user-actionable worker failure with stable code and retryability."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        if not code or not re.fullmatch(r"[A-Z0-9_.-]{1,96}", code):
            raise ValueError("worker error code must be a stable uppercase identifier")
        self.details = dict(details or {})
        _assert_json_compatible(self.details, "error details")
        self.code = code
        self.retryable = retryable


def _reject_constant(value: str) -> None:
    raise ValueError("non-standard JSON numeric constant is forbidden: " + value)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key is forbidden: " + key)
        result[key] = value
    return result


def _assert_json_compatible(value: Any, path: str = "value") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(path + " contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(path + " has a non-string object key")
            _assert_json_compatible(item, path + "." + key)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_json_compatible(item, path + "[" + str(index) + "]")
        return
    raise TypeError(path + " contains a value that is not JSON-compatible")


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")  # noqa: UP017


def read_task(path: Path, expected_operation: str | None = None) -> dict[str, Any]:
    """Read and validate the generic worker envelope without importing platform models."""
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkerFailure(
            "WORKER.REQUEST_INVALID",
            "task request is unreadable or is not strict JSON: " + str(exc),
        ) from exc
    if not isinstance(payload, dict):
        raise WorkerFailure("WORKER.REQUEST_INVALID", "task request must be a JSON object")
    if payload.get("protocol") != PROTOCOL_VERSION:
        raise WorkerFailure(
            "WORKER.PROTOCOL_MISMATCH",
            "task request protocol is missing or unsupported",
        )
    task_id = payload.get("task_id")
    operation = payload.get("operation")
    body = payload.get("payload")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise WorkerFailure("WORKER.REQUEST_INVALID", "task_id is missing or malformed")
    if not isinstance(operation, str) or not _OPERATION.fullmatch(operation):
        raise WorkerFailure("WORKER.REQUEST_INVALID", "operation is missing or malformed")
    if not isinstance(body, dict):
        raise WorkerFailure("WORKER.REQUEST_INVALID", "payload must be a JSON object")
    if expected_operation is not None and operation != expected_operation:
        raise WorkerFailure(
            "WORKER.OPERATION_MISMATCH",
            "task operation does not match this worker",
            details={"expected": expected_operation, "received": operation},
        )
    return payload


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write strict JSON by fsync + atomic replace, cleaning a partial file on error."""
    _assert_json_compatible(payload)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(path.parent),
            prefix="." + path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary)


class EventReporter:
    """Append sequenced, timestamped worker events as newline-delimited JSON."""

    def __init__(self, stream: TextIO, task_id: str | None) -> None:
        self._stream = stream
        self._task_id = task_id
        self._sequence = 0

    def set_task_id(self, task_id: str) -> None:
        """Associate subsequent events with the validated task identity."""
        if not _TASK_ID.fullmatch(task_id):
            raise WorkerFailure("WORKER.REQUEST_INVALID", "task_id is malformed")
        self._task_id = task_id

    def emit(
        self,
        event_type: str,
        message: str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        if event_type not in _EVENT_TYPES:
            raise WorkerFailure("WORKER.EVENT_INVALID", "unsupported worker event type")
        if not isinstance(message, str) or len(message) > 4096:
            raise WorkerFailure("WORKER.EVENT_INVALID", "event message must be <=4096 characters")
        self._sequence += 1
        event = {
            "protocol": PROTOCOL_VERSION,
            "task_id": self._task_id,
            "sequence": self._sequence,
            "timestamp": _iso_utc(),
            "type": event_type,
            "message": message,
            "data": dict(data or {}),
        }
        try:
            encoded = json.dumps(event, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            self._sequence -= 1
            raise WorkerFailure(
                "WORKER.EVENT_INVALID",
                "event data must contain only finite JSON values",
            ) from exc
        self._stream.write(encoded + "\n")
        self._stream.flush()


def run_task(
    task_path: Path,
    output_directory: Path,
    handler: Callable[[dict[str, Any], EventReporter], Mapping[str, Any]],
    *,
    expected_operation: str | None = None,
) -> int:
    """Run a handler and persist a completed/failed result plus its event stream."""
    output_directory.mkdir(parents=True, exist_ok=True)
    root = output_directory.resolve(strict=True)
    if not root.is_dir() or output_directory.is_symlink():
        raise ValueError("worker output directory must be a real directory, not a symlink")
    result_path = root / "result.json"
    events_path = root / "events.jsonl"
    if (
        result_path.exists()
        or result_path.is_symlink()
        or events_path.exists()
        or events_path.is_symlink()
    ):
        raise FileExistsError("worker result/event output already exists; refusing overwrite")

    started_clock = time.perf_counter()
    started_at = _iso_utc()
    task_id: str | None = None
    request: dict[str, Any] | None = None
    with events_path.open("x", encoding="utf-8", newline="\n") as stream:
        reporter = EventReporter(stream, task_id)
        reporter.emit("log", "worker started")
        try:
            request = read_task(task_path, expected_operation=expected_operation)
            task_id = request["task_id"]
            reporter.set_task_id(task_id)
            reporter.emit("log", "request validated", {"operation": request["operation"]})
            result = handler(request, reporter)
            if not isinstance(result, Mapping):
                raise WorkerFailure(
                    "WORKER.RESULT_INVALID",
                    "worker handler must return a JSON object",
                )
            envelope = {
                "protocol": PROTOCOL_VERSION,
                "task_id": task_id,
                "operation": request["operation"],
                "status": "completed",
                "started_at": started_at,
                "finished_at": _iso_utc(),
                "runtime_seconds": time.perf_counter() - started_clock,
                "result": dict(result),
            }
            write_json_atomic(result_path, envelope)
            reporter.emit("log", "worker completed")
            return 0
        except WorkerFailure as exc:
            error = {
                "code": exc.code,
                "type": type(exc).__name__,
                "message": str(exc),
                "retryable": exc.retryable,
                "details": exc.details,
            }
            return _write_failure(
                result_path, reporter, task_id, request, error, started_at, started_clock
            )
        except Exception as exc:
            error = {
                "code": "WORKER.UNEXPECTED",
                "type": type(exc).__name__,
                "message": str(exc) or type(exc).__name__,
                "retryable": False,
                "details": {},
            }
            traceback.print_exc(file=sys.stderr)
            return _write_failure(
                result_path, reporter, task_id, request, error, started_at, started_clock
            )


def _write_failure(
    result_path: Path,
    reporter: EventReporter,
    task_id: str | None,
    request: dict[str, Any] | None,
    error: dict[str, Any],
    started_at: str,
    started_clock: float,
) -> int:
    operation = request.get("operation") if request is not None else None
    envelope = {
        "protocol": PROTOCOL_VERSION,
        "task_id": task_id,
        "operation": operation,
        "status": "failed",
        "started_at": started_at,
        "finished_at": _iso_utc(),
        "runtime_seconds": time.perf_counter() - started_clock,
        "error": error,
    }
    write_json_atomic(result_path, envelope)
    reporter.emit("warning", error["message"], {"code": error["code"]})
    return 1


def main(
    handler: Callable[[dict[str, Any], EventReporter], Mapping[str, Any]],
    expected_operation: str,
    argv: list[str] | None = None,
) -> int:
    """Small CLI entry point used by isolated worker scripts."""
    parser = argparse.ArgumentParser(description="Run one isolated CADD Suite worker task")
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return run_task(
            args.task,
            args.output_dir,
            handler,
            expected_operation=expected_operation,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "protocol": PROTOCOL_VERSION,
                    "status": "failed-before-run",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
