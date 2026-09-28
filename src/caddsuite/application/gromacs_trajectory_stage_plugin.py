"""Discovered workflow stage for hash-linked GROMACS trajectory processing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from caddsuite.adapters.analysis.gromacs_trajectory import (
    GromacsTrajectoryProcessor,
    GromacsTrajectoryProcessorParameters,
)
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.planned_stage_runtime import confined_output, execute_adapter_plan
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.analysis import (
    TrajectoryProcessingRequest,
    TrajectoryProcessingResult,
)
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.execution import SoftwareEnvironment
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class GromacsTrajectoryStageHandler:
    adapter_id = "caddsuite.trajectory.gromacs"
    adapter_version = "0.1.0"

    def __init__(
        self,
        settings: GromacsTrajectoryProcessorParameters,
        *,
        engine_version: str,
        software_environment: SoftwareEnvironment | None,
        services: LocalRuntimeServices,
    ) -> None:
        self.settings = settings
        self.engine = GromacsTrajectoryProcessor()
        self.engine_version = engine_version
        self.software_environment = software_environment
        self.services = services

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if not isinstance(value, TrajectoryProcessingRequest):
            raise TypeError("processing fan-out requires TrajectoryProcessingRequest")
        return str(value.simulation_id)

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        request = _one(inputs, "request", TrajectoryProcessingRequest)
        refs = {
            "topology": request.topology,
            **{
                f"segment_{index:03d}": segment.artifact
                for index, segment in enumerate(request.segments, start=1)
            },
        }
        if self.settings.index_artifact is not None:
            refs["index"] = self.settings.index_artifact
        return {name: artifact.sha256 or "" for name, artifact in refs.items()}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> TrajectoryProcessingResult:
        request = _one(invocation.inputs, "request", TrajectoryProcessingRequest)
        refs = {
            str(request.topology.artifact_id): request.topology,
            **{str(segment.artifact.artifact_id): segment.artifact for segment in request.segments},
        }
        if self.settings.index_artifact is not None:
            refs[str(self.settings.index_artifact.artifact_id)] = self.settings.index_artifact

        parameters = self.settings.model_dump(mode="json")
        parameters["input_paths"] = {
            artifact_id: _input_relative_path(
                artifact_id, ref, request, self.settings.index_artifact
            )
            for artifact_id, ref in refs.items()
        }
        blockers = [
            issue
            for issue in self.engine.validate_request(request, parameters)
            if issue.severity.blocks_execution
        ]
        if blockers:
            raise StageExecutionFailure(blockers[0].code, blockers[0].message)

        work = self.services.run_root / f"trajectory-processing-{new_ulid()}"
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
        for artifact_id, artifact in refs.items():
            if artifact.sha256 is None or not self.services.artifacts.verify(artifact.sha256):
                raise StageExecutionFailure(
                    "MD.TRAJECTORY_ARTIFACT_INVALID",
                    f"artifact {artifact.role!r} is missing or failed hash verification",
                )
            relative = parameters["input_paths"][artifact_id]
            if not isinstance(relative, str):
                raise StageExecutionFailure(
                    "MD.TRAJECTORY_INPUT_PATHS", "derived trajectory input path is invalid"
                )
            destination = work / relative
            if not destination.resolve(strict=False).is_relative_to(work.resolve(strict=True)):
                raise StageExecutionFailure(
                    "MD.TRAJECTORY_INPUT_PATHS", "derived trajectory input escaped the stage"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.services.artifacts.path_for(artifact.sha256), destination)

        request_payload = self.engine.worker_request(request, parameters)
        request_path = work / self.settings.request_path
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(request_payload, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        plan = self.engine.plan_request(request, parameters, working_directory=work)
        outputs = execute_adapter_plan(
            self.services,
            plan,
            work,
            timeout_seconds=self.settings.timeout_seconds,
            artifact_kind="trajectory_processing_output",
            error_prefix="MD.TRAJECTORY",
        )
        result_relative = f"{self.settings.output_dir}/result.json"
        result_path = confined_output(work, result_relative, "MD.GROMACS_TRAJECTORY")
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageExecutionFailure(
                "MD.GROMACS_TRAJECTORY_RESULT_INVALID", f"worker result is unreadable: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise StageExecutionFailure(
                "MD.GROMACS_TRAJECTORY_RESULT_INVALID", "worker result must be a JSON object"
            )
        records = raw.get("outputs")
        if not isinstance(records, list):
            raise StageExecutionFailure(
                "MD.GROMACS_TRAJECTORY_RESULT_OUTPUTS", "worker output list is invalid"
            )
        output_artifacts: dict[str, ArtifactRef] = {}
        for item in records:
            if not isinstance(item, dict):
                raise StageExecutionFailure(
                    "MD.GROMACS_TRAJECTORY_RESULT_OUTPUTS", "worker output record is malformed"
                )
            role, relative = item.get("role"), item.get("path")
            if not isinstance(role, str) or not isinstance(relative, str):
                raise StageExecutionFailure(
                    "MD.GROMACS_TRAJECTORY_RESULT_OUTPUTS", "worker output role/path is invalid"
                )
            planned_path = f"{self.settings.output_dir}/{relative}"
            output_ref = outputs.get(planned_path)
            if output_ref is None:
                raise StageExecutionFailure(
                    "MD.GROMACS_TRAJECTORY_RESULT_OUTPUTS",
                    f"worker output {role!r} is absent from the declared plan",
                )
            output_artifacts[role] = output_ref
        command_log = outputs.get(f"{self.settings.output_dir}/commands.json")
        if command_log is None:
            raise StageExecutionFailure(
                "MD.GROMACS_TRAJECTORY_RESULT_LOGS", "commands.json output is missing"
            )
        extra_sources = (
            {"index": self.settings.index_artifact}
            if self.settings.index_artifact is not None
            else {}
        )
        return self.engine.normalize_result(
            request,
            raw,
            output_artifacts=output_artifacts,
            log_artifacts={"commands": command_log},
            additional_source_artifacts=extra_sources,
        )


class GromacsTrajectoryStagePlugin:
    plugin_id = "caddsuite.stage_handlers.gromacs_trajectory"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="trajectory.process",
            engine="gromacs",
            inputs=(
                CapabilityInput(
                    name="request", contracts=(TrajectoryProcessingRequest.schema_id(),)
                ),
            ),
            outputs=(TrajectoryProcessingResult.schema_id(),),
        )
        return (StageHandlerRegistration(capability, self._build, self._preflight),)

    @staticmethod
    def _settings(stage: StageDefinition) -> GromacsTrajectoryProcessorParameters:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise ValueError("GROMACS trajectory stage requires engine_parameters")
        values = dict(raw)
        # Input artifact IDs are run-specific and are derived from the normalized request.
        values.setdefault("input_paths", {"runtime-placeholder": "inputs/placeholder.dat"})
        return GromacsTrajectoryProcessorParameters.model_validate(values)

    @classmethod
    def _preflight(cls, stage: StageDefinition) -> EnginePreflightResult:
        try:
            settings = cls._settings(stage)
            gmx = _resolve_executable(settings.gmx_executable)
            python = _resolve_executable(settings.python_executable)
            version_probe = subprocess.run(  # noqa: S603 - configured binary, fixed argv
                [gmx, "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
            worker_probe = subprocess.run(  # noqa: S603 - configured Python, fixed import probe
                [python, "-c", "import caddsuite_worker.gromacs_trajectory_worker"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return EnginePreflightResult(
                "unavailable", reason=f"GROMACS trajectory preflight failed: {exc}"
            )
        version = version_probe.stdout.strip() or version_probe.stderr.strip()
        if version_probe.returncode or not version or worker_probe.returncode:
            return EnginePreflightResult(
                "unavailable",
                reason=(
                    version_probe.stderr.strip()
                    or worker_probe.stderr.strip()
                    or "GROMACS trajectory preflight failed"
                )[-2000:],
            )
        return EnginePreflightResult("available", engine_version=version)

    @classmethod
    def _build(cls, stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        settings = cls._settings(stage)
        gmx = _resolve_executable(settings.gmx_executable)
        python = _resolve_executable(settings.python_executable)
        probe = subprocess.run(  # noqa: S603 - configured binary, fixed version argv
            [gmx, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            shell=False,
        )
        version = probe.stdout.strip() or probe.stderr.strip()
        if not version:
            raise ValueError("GROMACS version probe returned no version")
        settings = settings.model_copy(
            update={
                "gmx_executable": gmx,
                "python_executable": python,
                "input_paths": {"runtime-placeholder": "inputs/placeholder.dat"},
            }
        )
        environment = capture_conda_environment(Path(python).resolve().parent.parent, services)
        return GromacsTrajectoryStageHandler(
            settings,
            engine_version=version,
            software_environment=environment,
            services=services,
        )


def plugin_factory() -> GromacsTrajectoryStagePlugin:
    return GromacsTrajectoryStagePlugin()


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "MD.TRAJECTORY_STAGE_INPUT", f"input {name!r} requires one {expected.__name__}"
        )
    return values[0]


def _input_relative_path(
    artifact_id: str,
    artifact: ArtifactRef,
    request: TrajectoryProcessingRequest,
    index_artifact: ArtifactRef | None = None,
) -> str:
    if index_artifact is not None and artifact == index_artifact:
        extension = "NDX"
    elif artifact == request.topology:
        extension = request.topology_format
    else:
        extension = request.trajectory_format
    suffix = {
        "gromacs tpr": "tpr",
        "gromacs_tpr": "tpr",
    }.get(extension.casefold(), extension.casefold())
    if not suffix.isalnum():
        raise StageExecutionFailure(
            "MD.TRAJECTORY_FORMAT_INVALID", "request contains an unsafe file format"
        )
    return f"inputs/{artifact_id}.{suffix}"


def _resolve_executable(value: str) -> str:
    candidate = Path(value).expanduser()
    resolved = (
        shutil.which(value) if not candidate.is_absolute() else str(candidate.resolve(strict=True))
    )
    if resolved is None or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"configured executable is unavailable: {value!r}")
    return resolved
