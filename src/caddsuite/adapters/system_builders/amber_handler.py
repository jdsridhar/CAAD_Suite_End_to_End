"""Local execution handler for the process-isolated AmberTools system builder."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from caddsuite.adapters.system_builders.amber_tleap import (
    AmberTLeapBuilderAdapter,
    AmberTLeapBuildError,
)
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.system import SystemBuildRequest, SystemBuildResult
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.local import CommandSpec, LocalExecutor
from caddsuite.ports.adapters import AdapterContext
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation


class AmberTLeapBuilderHandler:
    """Materialize immutable inputs, execute one adapter plan, and register every output."""

    adapter_id = AmberTLeapBuilderAdapter.adapter_id
    adapter_version = AmberTLeapBuilderAdapter.version

    def __init__(
        self,
        *,
        adapter: AmberTLeapBuilderAdapter,
        work_root: Path,
        log_root: Path,
        engine_version: str,
        executor: LocalExecutor,
        artifact_store: ArtifactStore,
        sessions: sessionmaker[Session],
    ) -> None:
        self.adapter = adapter
        self.engine_version = engine_version
        self.executor = executor
        self.artifact_store = artifact_store
        self.sessions = sessions
        self.work_root = work_root.resolve()
        self.log_root = log_root.resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if isinstance(value, Complex):
            return str(value.id)
        if isinstance(value, SystemBuildRequest):
            return str(value.complex_id)
        raise TypeError(
            f"Amber system building requires a Complex or request, got {type(value).__name__}"
        )

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        request = self._request(inputs)
        values: dict[str, str] = {}
        for path, ref in request.source_artifacts.items():
            if ref.sha256 is None:
                raise ValueError(f"source artifact {path!r} has no SHA-256")
            values[f"source:{path}"] = ref.sha256
        return values

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        request = self._request(inputs)
        return (
            {"system_build.mode": request.mode, "system_build.adapter": self.adapter_id},
            frozenset({"system_build.mode", "system_build.adapter"}),
        )

    def execute(self, invocation: TaskInvocation) -> SystemBuildResult:
        request = self._request(invocation.inputs)
        complex_model = self._complex(invocation.inputs)
        stage_dir = self.work_root / f"{invocation.task.stage_id}-{new_ulid()}"
        stage_dir.mkdir(mode=0o700)
        self._materialize_inputs(request, stage_dir)
        context = self._context(request, complex_model, stage_dir)
        issues = self.adapter.validate_input(context)
        blocker = next((issue for issue in issues if issue.severity.blocks_execution), None)
        if blocker is not None:
            raise StageExecutionFailure(blocker.code, blocker.message)
        try:
            plan = self.adapter.plan(context)
        except AmberTLeapBuildError as exc:
            raise StageExecutionFailure(exc.code, str(exc)) from exc
        if len(plan.commands) != 1:
            raise StageExecutionFailure(
                "AMBER_BUILD.PLAN_INVALID",
                "AmberTools builder must produce exactly one worker command",
            )
        step = plan.commands[0]
        result = self.executor.start(
            CommandSpec(argv=step.argv, cwd=step.working_directory, env=step.environment),
            log_dir=self.log_root,
        ).wait()
        if result.exit_code != 0:
            message = self._failure_message(stage_dir, result.stderr)
            raise StageExecutionFailure(message[0], message[1])

        raw_outputs: dict[str, ArtifactRef] = {
            "amber_worker_request.json": self._register_file(
                stage_dir / "amber_worker_request.json",
                kind="amber_worker_request",
                media_type="application/json",
            ),
            "execution/stdout.log": result.stdout,
            "execution/stderr.log": result.stderr,
        }
        output_dir = stage_dir / "amber_outputs"
        if not output_dir.is_dir():
            raise StageExecutionFailure(
                "AMBER_BUILD.OUTPUT_DIRECTORY_MISSING",
                "worker output directory is missing",
            )
        for path in sorted(output_dir.rglob("*")):
            if path.is_symlink():
                raise StageExecutionFailure(
                    "AMBER_BUILD.OUTPUT_SYMLINK", "worker created an output symlink"
                )
            if path.is_file():
                try:
                    relative = path.relative_to(stage_dir).as_posix()
                except ValueError as exc:
                    raise StageExecutionFailure(
                        "AMBER_BUILD.OUTPUT_PATH", "worker output escaped its stage"
                    ) from exc
                raw_outputs[relative] = self._register_file(
                    path,
                    kind=f"amber_output_{path.name}",
                    media_type=self._media_type(path),
                )
        try:
            return self.adapter.normalize_result(raw_outputs, context)
        except AmberTLeapBuildError as exc:
            raise StageExecutionFailure(exc.code, str(exc)) from exc

    def _materialize_inputs(self, request: SystemBuildRequest, stage_dir: Path) -> None:
        for relative, ref in request.source_artifacts.items():
            path = PurePosixPath(relative)
            if (
                not relative
                or path.is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise StageExecutionFailure(
                    "AMBER_BUILD.UNSAFE_PATH", f"unsafe source path {relative!r}"
                )
            if ref.sha256 is None or not self.artifact_store.verify(ref.sha256):
                raise StageExecutionFailure(
                    "AMBER_BUILD.INPUT_ARTIFACT_INVALID",
                    f"source artifact {relative!r} is unavailable or fails its SHA-256 check",
                )
            destination = stage_dir.joinpath(*path.parts)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if destination.exists():
                raise StageExecutionFailure(
                    "AMBER_BUILD.INPUT_PATH_COLLISION",
                    f"duplicate staged path {relative!r}",
                )
            shutil.copyfile(self.artifact_store.path_for(ref.sha256), destination)
            if _sha256(destination) != ref.sha256:
                raise StageExecutionFailure(
                    "AMBER_BUILD.INPUT_COPY_HASH",
                    f"staged input {relative!r} failed SHA-256",
                )

    def _context(
        self, request: SystemBuildRequest, complex_model: Complex, stage_dir: Path
    ) -> AdapterContext:
        return AdapterContext(
            inputs={"request": request, "complex": complex_model},
            parameters=dict(request.parameters),
            working_directory=stage_dir,
        )

    def _failure_message(self, stage_dir: Path, stderr: ArtifactRef) -> tuple[str, str]:
        report_path = stage_dir / "amber_outputs/worker_result.json"
        if report_path.is_file():
            try:
                report = cast(dict[str, Any], json.loads(report_path.read_text(encoding="utf-8")))
                code = str(report.get("error_code", "AMBER_BUILD.WORKER_FAILED"))
                message = str(report.get("error", "AmberTools worker failed"))
                return code, message
            except (OSError, json.JSONDecodeError):
                pass
        detail = ""
        if stderr.sha256 is not None:
            with suppress(OSError):
                detail = self.artifact_store.path_for(stderr.sha256).read_text(
                    encoding="utf-8", errors="replace"
                )[-4000:]
        return (
            "AMBER_BUILD.WORKER_FAILED",
            "AmberTools worker exited unsuccessfully; inspect stderr and retained partial "
            f"outputs. {detail}",
        )

    def _register_file(self, path: Path, *, kind: str, media_type: str) -> ArtifactRef:
        blob = self.artifact_store.put_file(path)
        with self.sessions.begin() as session:
            row = register_blob(
                session,
                blob,
                kind=kind,
                media_type=media_type,
                original_name=path.name,
            )
            artifact_id = row.id
        return ArtifactRef(artifact_id=artifact_id, role=kind, sha256=blob.sha256)

    @staticmethod
    def _media_type(path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".json": "application/json",
            ".pdb": "chemical/x-pdb",
            ".mol2": "chemical/x-mol2",
            ".frcmod": "chemical/x-amber-parameter",
            ".prmtop": "chemical/x-amber-topology",
            ".inpcrd": "chemical/x-amber-coordinates",
            ".rst7": "chemical/x-amber-restart",
            ".gro": "chemical/x-gro",
            ".top": "chemical/x-gromacs-topology",
            ".ndx": "chemical/x-gromacs-index",
            ".xvg": "chemical/x-xvg",
            ".edr": "application/octet-stream",
            ".tpr": "application/octet-stream",
            ".mdp": "text/plain",
            ".in": "text/plain",
            ".log": "text/plain",
            ".lib": "chemical/x-amber-library",
            ".dat": "chemical/x-amber-parameter",
        }.get(suffix, "application/octet-stream")

    @staticmethod
    def _request(inputs: Mapping[str, tuple[VersionedContract, ...]]) -> SystemBuildRequest:
        values = [
            value
            for group in inputs.values()
            for value in group
            if isinstance(value, SystemBuildRequest)
        ]
        if len(values) != 1:
            raise ValueError(f"expected exactly one SystemBuildRequest, received {len(values)}")
        return values[0]

    @staticmethod
    def _complex(inputs: Mapping[str, tuple[VersionedContract, ...]]) -> Complex:
        values = [
            value for group in inputs.values() for value in group if isinstance(value, Complex)
        ]
        if len(values) != 1:
            raise ValueError(f"expected exactly one Complex, received {len(values)}")
        return values[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
