"""Shared safe execution and CAS registration for adapter-produced command plans."""

from __future__ import annotations

import mimetypes
import subprocess
from pathlib import Path, PurePosixPath

from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ArtifactRef
from caddsuite.domain.errors import ExecutionCancelled
from caddsuite.execution.attempt_context import record_generated_artifact
from caddsuite.execution.local import CommandSpec, ExecutionError
from caddsuite.storage.artifacts import register_blob
from caddsuite.workflow.scheduler import StageExecutionFailure


def execute_adapter_plan(
    services: LocalRuntimeServices,
    plan: object,
    working_directory: Path,
    *,
    timeout_seconds: float,
    artifact_kind: str,
    error_prefix: str,
) -> dict[str, ArtifactRef]:
    """Run planned argv commands and register every declared output.

    Adapters own scientific validation, plan construction and normalization. This function
    enforces the private working directory, shell-free executor, timeout handling, output
    confinement, CAS registration, and generated-artifact provenance.
    """
    commands = getattr(plan, "commands", None)
    expected = getattr(plan, "expected_outputs", None)
    if not isinstance(commands, tuple) or not isinstance(expected, tuple) or not expected:
        raise StageExecutionFailure(
            f"{error_prefix}.PLAN_INVALID", "adapter returned an invalid execution plan"
        )
    root = working_directory.resolve(strict=True)
    for index, command in enumerate(commands):
        try:
            cwd = command.working_directory.resolve(strict=True)
        except OSError as exc:
            raise StageExecutionFailure(
                f"{error_prefix}.PLAN_INVALID", "adapter command directory is unavailable"
            ) from exc
        if not cwd.is_relative_to(root):
            raise StageExecutionFailure(
                f"{error_prefix}.PLAN_INVALID", "adapter command escaped its private work directory"
            )
        running = services.executor.start(
            CommandSpec(command.argv, cwd, command.environment),
            log_dir=root / "logs" / str(index),
        )
        try:
            result = running.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            running.cancel()
            raise StageExecutionFailure(
                f"{error_prefix}.TIMEOUT",
                f"adapter command {index} exceeded {timeout_seconds:g} seconds",
            ) from exc
        except ExecutionError as exc:
            raise StageExecutionFailure(f"{error_prefix}.EXECUTION_ERROR", str(exc)) from exc
        except ExecutionCancelled:
            raise
        if result.exit_code != 0:
            raise StageExecutionFailure(
                f"{error_prefix}.ENGINE_FAILURE",
                f"adapter command {index} exited with status {result.exit_code}; inspect logs",
            )

    refs: dict[str, ArtifactRef] = {}
    for relative in expected:
        if not isinstance(relative, str):
            raise StageExecutionFailure(
                f"{error_prefix}.PLAN_INVALID", "planned output path must be text"
            )
        path = _confined_output(root, relative, error_prefix)
        if path.is_symlink() or not path.is_file():
            raise StageExecutionFailure(
                f"{error_prefix}.OUTPUT_MISSING", f"planned output is missing: {relative}"
            )
        blob = services.artifacts.put_file(path)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with services.sessions.begin() as session:
            row = register_blob(
                session,
                blob,
                kind=artifact_kind,
                media_type=media_type,
                original_name=path.name,
            )
            ref = ArtifactRef(
                artifact_id=row.id,
                role=f"adapter_output_{path.suffix.lstrip('.') or 'data'}",
                sha256=row.sha256,
            )
        record_generated_artifact(ref, relative)
        refs[relative] = ref
    return refs


def confined_output(root: Path, relative: str, error_prefix: str) -> Path:
    """Resolve an adapter-declared output beneath its private work directory."""
    return _confined_output(root.resolve(strict=True), relative, error_prefix)


def _confined_output(root: Path, relative: str, error_prefix: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise StageExecutionFailure(
            f"{error_prefix}.PATH_INVALID", "adapter output path is not a confined relative path"
        )
    path = root.joinpath(*pure.parts).resolve(strict=False)
    if not path.is_relative_to(root):
        raise StageExecutionFailure(
            f"{error_prefix}.PATH_INVALID", "adapter output escaped its private work directory"
        )
    return path
