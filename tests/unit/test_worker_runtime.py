"""Tests for the stdlib-only isolated-worker request/result/event protocol."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caddsuite_worker import PROTOCOL_VERSION
from caddsuite_worker.runtime import WorkerFailure, run_task


def _task(path: Path, *, operation: str = "qm.psi4.single_point") -> Path:
    request = {
        "protocol": PROTOCOL_VERSION,
        "task_id": "01ABCDEF0123456789",
        "operation": operation,
        "payload": {"charge": 0, "multiplicity": 1},
    }
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def test_worker_runtime_writes_result_and_monotonic_jsonl_events(tmp_path: Path):
    task_path = _task(tmp_path / "task.json")
    output = tmp_path / "out"

    def handler(request, report):
        report.emit("progress", "SCF converged", {"iterations": 12})
        return {"energy_Eh": -40.123456}

    assert run_task(task_path, output, handler, expected_operation="qm.psi4.single_point") == 0
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["status"] == "completed"
    assert result["task_id"] == "01ABCDEF0123456789"
    assert result["result"]["energy_Eh"] == -40.123456
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert all(event["protocol"] == PROTOCOL_VERSION for event in events)
    assert events[2]["data"] == {"iterations": 12}


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        ("[]", "WORKER.REQUEST_INVALID"),
        ("{", "WORKER.REQUEST_INVALID"),
        (
            '{"protocol":"caddsuite.worker/999","task_id":"t","operation":"op","payload":{}}',
            "WORKER.PROTOCOL_MISMATCH",
        ),
        (
            '{"protocol":"caddsuite.worker/1","task_id":"t","operation":"op","payload":{"n":NaN}}',
            "WORKER.REQUEST_INVALID",
        ),
        (
            '{"protocol":"caddsuite.worker/1",'
            '"task_id":"t","task_id":"other","operation":"op","payload":{}}',
            "WORKER.REQUEST_INVALID",
        ),
    ],
)
def test_worker_runtime_reports_malformed_task_without_traceback(
    tmp_path: Path, raw: str, error_code: str, capsys
):
    task_path = tmp_path / "task.json"
    task_path.write_text(raw, encoding="utf-8")

    assert run_task(task_path, tmp_path / "out", lambda request, report: {}) == 1
    result = json.loads((tmp_path / "out/result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error"]["code"] == error_code
    assert result["error"]["retryable"] is False
    assert capsys.readouterr().err == ""


def test_worker_runtime_preserves_stable_actionable_worker_failure(tmp_path: Path):
    task_path = _task(tmp_path / "task.json")

    def handler(request, report):
        raise WorkerFailure(
            "PSI4.INPUT.INVALID",
            "molecular charge and electron count are inconsistent",
            details={"charge": 1},
        )

    assert run_task(task_path, tmp_path / "out", handler) == 1
    result = json.loads((tmp_path / "out/result.json").read_text(encoding="utf-8"))
    assert result["error"]["code"] == "PSI4.INPUT.INVALID"
    assert result["error"]["message"] == "molecular charge and electron count are inconsistent"
    assert result["error"]["details"] == {"charge": 1}


def test_worker_runtime_rejects_nonfinite_result_and_cleans_temp_files(tmp_path: Path):
    task_path = _task(tmp_path / "task.json")

    status = run_task(
        task_path,
        tmp_path / "out",
        lambda request, report: {"energy_Eh": float("nan")},
    )
    assert status == 1
    output = tmp_path / "out"
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert result["error"]["code"] == "WORKER.UNEXPECTED"
    assert not list(output.glob("*.tmp"))
    assert not list(output.glob(".result.json.*.tmp"))


def test_worker_runtime_rejects_operation_mismatch_and_refuses_overwrite(tmp_path: Path):
    task_path = _task(tmp_path / "task.json")

    assert (
        run_task(
            task_path,
            tmp_path / "first",
            lambda request, report: {},
            expected_operation="qm.psi4.optimize",
        )
        == 1
    )
    result = json.loads((tmp_path / "first/result.json").read_text(encoding="utf-8"))
    assert result["error"]["code"] == "WORKER.OPERATION_MISMATCH"

    with pytest.raises(FileExistsError, match="refusing overwrite"):
        run_task(task_path, tmp_path / "first", lambda request, report: {})
