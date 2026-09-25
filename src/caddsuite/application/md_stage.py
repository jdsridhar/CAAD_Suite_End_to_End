"""Application-layer execution of normalized MD stage plans."""

from __future__ import annotations

import mimetypes
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TypeVar

from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ArtifactRef, SoftwareRef, VersionedContract
from caddsuite.contracts.execution import ResourceRequest, SoftwareEnvironment
from caddsuite.contracts.md import MDStageInput, MDStageResult
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.domain.identity import new_ulid
from caddsuite.execution.attempt_context import record_generated_artifact
from caddsuite.execution.local import CommandSpec
from caddsuite.ports.adapters import AdapterContext
from caddsuite.ports.md_engine import MDExecutionEngine
from caddsuite.storage.artifacts import register_blob
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class MDExecutionStageHandler:
    """Run one engine-planned MD stage and return its versioned artifact receipt."""

    def __init__(
        self,
        engine: MDExecutionEngine,
        *,
        engine_version: str,
        engine_key: str,
        engine_name: str,
        parameters: Mapping[str, object],
        engine_parameters: Mapping[str, object],
        memory_MiB: int,
        software_environment: SoftwareEnvironment | None,
        services: LocalRuntimeServices,
    ) -> None:
        self.engine = engine
        self.engine_version = engine_version
        self.engine_key = engine_key
        self.engine_name = engine_name
        self.parameters = dict(parameters)
        self.engine_parameters = dict(engine_parameters)
        self.memory_MiB = memory_MiB
        self.software_environment = software_environment
        self.services = services
        self.adapter_id = engine.adapter_id
        self.adapter_version = engine.version

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if isinstance(value, SystemBuildResult):
            return str(value.system.id)
        if isinstance(value, MDStageInput):
            return str(value.system_id)
        raise TypeError(f"MD fan-out cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        hashes: dict[str, str] = {}
        for name, values in inputs.items():
            for index, contract in enumerate(values):
                refs: dict[str, ArtifactRef] = {}
                if isinstance(contract, MDStageInput):
                    refs = contract.artifacts
                elif isinstance(contract, SystemBuildResult):
                    refs = {
                        **contract.raw_artifacts,
                        **contract.normalized_artifacts,
                        **contract.system.engine_inputs.get(self.engine_key, {}),
                    }
                for role, ref in refs.items():
                    if ref.sha256 is not None:
                        hashes[f"{name}[{index}].{role}"] = ref.sha256
        return hashes

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def resource_request(self, invocation: TaskInvocation) -> ResourceRequest:
        del invocation
        raw_threads = self.parameters.get("cpu_threads", 1)
        threads = raw_threads if isinstance(raw_threads, int) and raw_threads > 0 else 1
        raw_gpus = self.parameters.get("gpu_ids", ())
        gpu_count = len(raw_gpus) if isinstance(raw_gpus, (tuple, list)) else 0
        return ResourceRequest(cpu_cores=threads, memory_MiB=self.memory_MiB, gpu_count=gpu_count)

    def execute(self, invocation: TaskInvocation) -> MDStageResult:
        build = _one(invocation.inputs, "system_build", SystemBuildResult)
        stage_input = _one(invocation.inputs, "stage_input", MDStageInput)
        if stage_input.system_id != build.system.id:
            raise StageExecutionFailure(
                "MD.STAGE_SYSTEM_MISMATCH", "stage input belongs to a different MD system"
            )
        work = self.services.run_root / f"md-{new_ulid()}"
        work.mkdir(mode=0o700, parents=True)
        context = AdapterContext(
            inputs={"system_build": build, "stage_input": stage_input},
            parameters={self.engine_key: self.parameters},
            working_directory=work,
        )
        blockers = tuple(
            issue
            for issue in self.engine.validate_stage(context)
            if issue.severity.blocks_execution
        )
        if blockers:
            issue = blockers[0]
            raise StageExecutionFailure(issue.code, issue.message)
        for relative_path, ref in self.engine.stage_input_artifacts(context).items():
            destination = _confined_path(work, relative_path)
            if ref.sha256 is None or not self.services.artifacts.verify(ref.sha256):
                raise StageExecutionFailure(
                    "MD.INPUT_ARTIFACT_INVALID",
                    f"input {relative_path!r} has no valid registered SHA-256 artifact",
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.services.artifacts.path_for(ref.sha256), destination)
        plan = self.engine.plan_stage(context)
        elapsed = 0.0
        for index, command in enumerate(plan.commands):
            command_cwd = command.working_directory.resolve()
            if command_cwd != work.resolve():
                raise StageExecutionFailure(
                    "MD.WORKING_DIRECTORY_INVALID",
                    "adapter command escaped its private stage working directory",
                )
            running = self.services.executor.start(
                CommandSpec(command.argv, command_cwd, command.environment),
                log_dir=work / "logs" / str(index),
            )
            try:
                execution = running.wait(timeout=self._timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                running.cancel()
                raise StageExecutionFailure(
                    "MD.ENGINE_TIMEOUT", f"MD command {index} exceeded its configured timeout"
                ) from exc
            elapsed += execution.duration_seconds
            if execution.exit_code != 0:
                raise StageExecutionFailure(
                    "MD.ENGINE_FAILURE",
                    f"MD command {index} exited with status {execution.exit_code}; "
                    "inspect attempt logs",
                )
            stdout = self.services.artifacts.path_for(execution.stdout.sha256 or "").read_bytes()
            stderr = self.services.artifacts.path_for(execution.stderr.sha256 or "").read_bytes()
            issues = self.engine.validate_execution_step(context, index, stdout, stderr)
            blocking = tuple(issue for issue in issues if issue.severity.blocks_execution)
            if blocking:
                raise StageExecutionFailure(blocking[0].code, blocking[0].message)
        outputs = self._collect_outputs(work, plan.expected_outputs)
        if not outputs:
            raise StageExecutionFailure(
                "MD.OUTPUTS_MISSING", "MD engine completed without any declared output artifacts"
            )
        protocol = build.protocol
        if protocol is None:
            raise StageExecutionFailure("MD.PROTOCOL_MISSING", "MD system has no protocol")
        raw_stage_index = self.parameters.get("stage_index")
        stage_index = raw_stage_index if isinstance(raw_stage_index, int) else -1
        if not 0 <= stage_index < len(protocol.stages):
            raise StageExecutionFailure("MD.STAGE_INDEX_INVALID", "stage index is outside protocol")
        raw_segment = self.parameters.get("segment_index", 1)
        segment_index = raw_segment if isinstance(raw_segment, int) else 1
        result = MDStageResult(
            id=new_ulid(),
            system_id=build.system.id,
            stage_input_id=stage_input.id,
            stage_index=stage_index,
            segment_index=segment_index,
            stage_kind=protocol.stages[stage_index].kind,
            engine=SoftwareRef(name=self.engine_name, version=self.engine_version, kind="engine"),
            adapter=SoftwareRef(name=self.adapter_id, version=self.adapter_version, kind="adapter"),
            parameters=self.engine_parameters,
            runtime_seconds=elapsed,
            artifacts=outputs,
        )
        return result

    def _collect_outputs(self, work: Path, declared: tuple[str, ...]) -> dict[str, ArtifactRef]:
        candidates = {_confined_path(work, name) for name in declared}
        missing = sorted(name for name in declared if not _confined_path(work, name).is_file())
        if missing:
            raise StageExecutionFailure(
                "MD.OUTPUTS_MISSING", f"MD engine omitted declared output(s): {missing}"
            )
        prefix = self.parameters.get("output_prefix")
        if isinstance(prefix, str):
            candidates.update(path for path in work.glob(f"{prefix}.*") if path.is_file())
        refs: dict[str, ArtifactRef] = {}
        for path in sorted(candidates):
            if not path.is_file():
                continue
            suffix = path.suffix.lower().lstrip(".") or "output"
            role = f"md_{suffix}"
            blob = self.services.artifacts.put_file(path)
            with self.services.sessions.begin() as session:
                row = register_blob(
                    session,
                    blob,
                    kind="md_output",
                    media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    original_name=path.name,
                )
                ref = ArtifactRef(artifact_id=row.id, role=role, sha256=row.sha256)
            record_generated_artifact(ref, role)
            refs[f"{role}_{len(refs) + 1}"] = ref
        return refs

    @property
    def _timeout_seconds(self) -> float | None:
        value = self.engine_parameters.get("timeout_seconds")
        return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "MD.INPUT_CONTRACT_INVALID", f"input {name!r} requires one {expected.__name__}"
        )
    return values[0]


def _confined_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise StageExecutionFailure(
            "MD.INPUT_PATH_INVALID", f"MD input path is not a confined relative path: {relative!r}"
        )
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise StageExecutionFailure("MD.INPUT_PATH_INVALID", "MD input escaped stage directory")
    return path
