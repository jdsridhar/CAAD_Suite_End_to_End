from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import pytest

from caddsuite.application.planned_stage_runtime import execute_adapter_plan
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler


def _runtime(tmp_path: Path) -> LocalWorkflowRuntime:
    return LocalWorkflowRuntime.open(
        data_root=tmp_path / "runtime",
        handlers=lambda _services: {"unused": cast(StageHandler, object())},
    )


def test_adapter_plan_runner_registers_outputs_in_cas(tmp_path: Path) -> None:
    with _runtime(tmp_path) as runtime:
        work = runtime.services.run_root / "stage"
        work.mkdir()
        plan = ExecutionPlan(
            commands=(
                CommandStep(
                    argv=(
                        sys.executable,
                        "-c",
                        "from pathlib import Path; "
                        "Path('result.json').write_text('{\\\"ok\\\":true}')",
                    ),
                    working_directory=work,
                    environment={},
                ),
            ),
            expected_outputs=("result.json",),
        )
        refs = execute_adapter_plan(
            runtime.services,
            plan,
            work,
            timeout_seconds=10,
            artifact_kind="test_output",
            error_prefix="TEST.ADAPTER",
        )
        ref = refs["result.json"]
        assert ref.sha256 is not None
        assert runtime.services.artifacts.verify(ref.sha256)
        assert runtime.services.artifacts.path_for(ref.sha256).read_text() == '{"ok":true}'


def test_adapter_plan_runner_rejects_escaping_output_path(tmp_path: Path) -> None:
    with _runtime(tmp_path) as runtime:
        work = runtime.services.run_root / "stage"
        work.mkdir()
        plan = ExecutionPlan(commands=(), expected_outputs=("../outside.txt",))
        with pytest.raises(StageExecutionFailure, match="confined"):
            execute_adapter_plan(
                runtime.services,
                plan,
                work,
                timeout_seconds=10,
                artifact_kind="test_output",
                error_prefix="TEST.ADAPTER",
            )


def test_adapter_plan_runner_reports_missing_planned_output(tmp_path: Path) -> None:
    with _runtime(tmp_path) as runtime:
        work = runtime.services.run_root / "stage"
        work.mkdir()
        plan = ExecutionPlan(commands=(), expected_outputs=("missing.txt",))
        with pytest.raises(StageExecutionFailure, match="planned output is missing"):
            execute_adapter_plan(
                runtime.services,
                plan,
                work,
                timeout_seconds=10,
                artifact_kind="test_output",
                error_prefix="TEST.ADAPTER",
            )


def test_adapter_plan_runner_rejects_nonzero_exit_and_preserves_logs(tmp_path: Path) -> None:
    with _runtime(tmp_path) as runtime:
        work = runtime.services.run_root / "stage"
        work.mkdir()
        plan = ExecutionPlan(
            commands=(
                CommandStep(
                    argv=(sys.executable, "-c", "raise SystemExit(9)"),
                    working_directory=work,
                    environment={},
                ),
            ),
            expected_outputs=("unused.txt",),
        )
        with pytest.raises(StageExecutionFailure, match="status 9"):
            execute_adapter_plan(
                runtime.services,
                plan,
                work,
                timeout_seconds=10,
                artifact_kind="test_output",
                error_prefix="TEST.ADAPTER",
            )
        logs = list((work / "logs").glob("*/*.stderr.log"))
        assert logs
