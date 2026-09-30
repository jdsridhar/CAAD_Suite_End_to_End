"""Discovered PDB/DCD validation-only trajectory processor backed by MDAnalysis."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TypeVar

from caddsuite.adapters.analysis.mdanalysis_trajectory import (
    MDAnalysisTrajectoryProcessor,
    MDAnalysisTrajectoryProcessorParameters,
)
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.planned_stage_runtime import confined_output, execute_adapter_plan
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.analysis import TrajectoryProcessingRequest, TrajectoryProcessingResult
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.execution import SoftwareEnvironment
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class MDAnalysisTrajectoryStageHandler:
    adapter_id = "caddsuite.trajectory.mdanalysis"
    adapter_version = "0.1.0"

    def __init__(
        self,
        settings: MDAnalysisTrajectoryProcessorParameters,
        *,
        engine_version: str,
        software_environment: SoftwareEnvironment | None,
        services: LocalRuntimeServices,
    ) -> None:
        self.settings = settings
        self.engine_version = engine_version
        self.software_environment = software_environment
        self.services = services
        self.engine = MDAnalysisTrajectoryProcessor()

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if not isinstance(value, TrajectoryProcessingRequest):
            raise TypeError("trajectory processor fan-out requires a processing request")
        return str(value.simulation_id)

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        request = _one(inputs, "request", TrajectoryProcessingRequest)
        return {
            "topology": request.topology.sha256 or "",
            **{
                f"segment_{index:03d}": segment.artifact.sha256 or ""
                for index, segment in enumerate(request.segments, start=1)
            },
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> TrajectoryProcessingResult:
        request = _one(invocation.inputs, "request", TrajectoryProcessingRequest)
        inputs = {
            str(request.topology.artifact_id): request.topology,
            **{str(item.artifact.artifact_id): item.artifact for item in request.segments},
        }
        parameters = self.settings.model_dump(mode="json")
        parameters["input_paths"] = {
            artifact_id: _input_path(request, artifact_id, artifact)
            for artifact_id, artifact in inputs.items()
        }
        blockers = [
            issue
            for issue in self.engine.validate_request(request, parameters)
            if issue.severity.blocks_execution
        ]
        if blockers:
            raise StageExecutionFailure(blockers[0].code, blockers[0].message)

        work = self.services.run_root / f"mdanalysis-trajectory-{new_ulid()}"
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
        for artifact_id, artifact in inputs.items():
            digest = artifact.sha256
            if digest is None or not self.services.artifacts.verify(digest):
                raise StageExecutionFailure(
                    "MD.MDA_TRAJECTORY_ARTIFACT_INVALID",
                    f"artifact {artifact.role!r} is missing or fails SHA-256 verification",
                )
            relative = parameters["input_paths"][artifact_id]
            if not isinstance(relative, str):
                raise StageExecutionFailure(
                    "MD.MDA_TRAJECTORY_INPUT_PATH", "derived artifact path is invalid"
                )
            destination = work.joinpath(*PurePosixPath(relative).parts)
            if not destination.resolve(strict=False).is_relative_to(work.resolve(strict=True)):
                raise StageExecutionFailure(
                    "MD.MDA_TRAJECTORY_INPUT_PATH", "derived artifact path escaped the job root"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.services.artifacts.path_for(digest), destination)

        request_payload = self.engine.worker_request(request, parameters)
        request_path = work.joinpath(*PurePosixPath(self.settings.request_path).parts)
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
            artifact_kind="trajectory_processing_receipt",
            error_prefix="MD.MDA_TRAJECTORY",
        )
        receipt_ref = outputs.get(self.settings.output_path)
        if receipt_ref is None:
            raise StageExecutionFailure(
                "MD.MDA_TRAJECTORY_RECEIPT_MISSING", "worker JSON receipt was not registered"
            )
        receipt_path = confined_output(work, self.settings.output_path, "MD.MDA_TRAJECTORY")
        try:
            raw = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageExecutionFailure(
                "MD.MDA_TRAJECTORY_RECEIPT_INVALID", f"worker receipt is unreadable: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise StageExecutionFailure(
                "MD.MDA_TRAJECTORY_RECEIPT_INVALID", "worker receipt must be a JSON object"
            )
        return self.engine.normalize_result(
            request,
            raw,
            output_artifacts={"receipt": receipt_ref},
            log_artifacts={},
        )


class MDAnalysisTrajectoryStagePlugin:
    plugin_id = "caddsuite.stage_handlers.mdanalysis_trajectory"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="trajectory.process",
            engine="mdanalysis",
            inputs=(
                CapabilityInput(
                    name="request",
                    contracts=(TrajectoryProcessingRequest.schema_id(),),
                ),
            ),
            outputs=(TrajectoryProcessingResult.schema_id(),),
        )
        return (StageHandlerRegistration(capability, self._build, self._preflight),)

    @staticmethod
    def _settings(stage: StageDefinition) -> MDAnalysisTrajectoryProcessorParameters:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise ValueError("MDAnalysis trajectory stage requires engine_parameters")
        return MDAnalysisTrajectoryProcessorParameters.model_validate(dict(raw))

    @classmethod
    def _preflight(cls, stage: StageDefinition) -> EnginePreflightResult:
        try:
            settings = cls._settings(stage)
            python = _resolve_executable(settings.python_executable)
            probe = subprocess.run(  # noqa: S603 - resolved executable and constant probe argv
                [python, "-c", "import MDAnalysis; print(MDAnalysis.__version__)"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                shell=False,
            )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return EnginePreflightResult("unavailable", reason=f"MDAnalysis probe failed: {exc}")
        version = probe.stdout.strip().splitlines()
        if probe.returncode != 0 or not version:
            return EnginePreflightResult(
                "unavailable", reason=(probe.stderr.strip() or "MDAnalysis import failed")[-2000:]
            )
        return EnginePreflightResult("available", engine_version=version[-1])

    @classmethod
    def _build(cls, stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        settings = cls._settings(stage)
        python = _resolve_executable(settings.python_executable)
        worker = Path(settings.worker_script).expanduser().resolve(strict=True)
        if not worker.is_file():
            raise ValueError("MDAnalysis trajectory worker is not a regular file")
        probe = subprocess.run(  # noqa: S603 - resolved executable and constant probe argv
            [python, "-c", "import MDAnalysis; print(MDAnalysis.__version__)"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            shell=False,
        )
        version = probe.stdout.strip().splitlines()
        if not version:
            raise ValueError("MDAnalysis version probe returned no version")
        settings = settings.model_copy(
            update={"python_executable": python, "worker_script": str(worker)}
        )
        environment = capture_conda_environment(Path(python).resolve().parent.parent, services)
        return MDAnalysisTrajectoryStageHandler(
            settings,
            engine_version=version[-1],
            software_environment=environment,
            services=services,
        )


def plugin_factory() -> MDAnalysisTrajectoryStagePlugin:
    return MDAnalysisTrajectoryStagePlugin()


def _input_path(
    request: TrajectoryProcessingRequest, artifact_id: str, artifact: ArtifactRef
) -> str:
    if artifact == request.topology:
        extension = request.topology_format
    else:
        extension = request.trajectory_format
    if not extension.isalnum():
        raise StageExecutionFailure(
            "MD.MDA_TRAJECTORY_FORMAT_INVALID", "input format contains unsafe path characters"
        )
    return f"inputs/{artifact_id}.{extension.casefold()}"


def _resolve_executable(value: str) -> str:
    candidate = Path(value).expanduser()
    resolved = (
        shutil.which(value) if not candidate.is_absolute() else str(candidate.resolve(strict=True))
    )
    if resolved is None or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"configured Python interpreter is unavailable: {value!r}")
    return resolved


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "MD.MDA_TRAJECTORY_INPUT", f"input {name!r} requires one {expected.__name__}"
        )
    return values[0]
