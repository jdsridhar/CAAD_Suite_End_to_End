"""Production workflow stage for the capability-limited MDAnalysis metrics adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TypeVar

from caddsuite.adapters.analysis.mdanalysis_metrics import (
    MDAnalysisMetricsAdapter,
    MDAnalysisMetricsParameters,
)
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.planned_stage_runtime import execute_adapter_plan
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.analysis import (
    TrajectoryAnalysisPlan,
    TrajectoryAnalysisRequest,
    TrajectoryAnalysisResult,
    TrajectoryProcessingResult,
)
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.execution import SoftwareEnvironment
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class MDAnalysisStageHandler:
    """Materialize hash-verified inputs, execute the adapter plan, normalize its metrics."""

    adapter_id = "caddsuite.mdanalysis.metrics"
    adapter_version = "0.1.0"
    engine_name = "MDAnalysis"

    def __init__(
        self,
        settings: MDAnalysisMetricsParameters,
        *,
        engine_version: str,
        software_environment: SoftwareEnvironment | None,
        services: LocalRuntimeServices,
    ) -> None:
        self.settings = settings
        self.engine = MDAnalysisMetricsAdapter()
        self.engine_version = engine_version
        self.software_environment = software_environment
        self.services = services

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if isinstance(value, TrajectoryAnalysisPlan):
            return str(value.simulation_id)
        if isinstance(value, TrajectoryAnalysisRequest):
            return str(value.simulation_id)
        raise TypeError("analysis fan-out requires a trajectory analysis plan or request")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        parent = _one(inputs, "preprocessing", TrajectoryProcessingResult)
        plan_values = inputs.get("analysis_plan", ())
        if plan_values:
            import hashlib
            import json

            plan = _one(inputs, "analysis_plan", TrajectoryAnalysisPlan)
            serialized = json.dumps(
                plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            return {
                "plan": hashlib.sha256(serialized.encode()).hexdigest(),
                **{
                    f"processed.{key}": ref.sha256 or ""
                    for key, ref in parent.output_artifacts.items()
                },
            }
        request = _one(inputs, "request", TrajectoryAnalysisRequest)
        refs = {
            "trajectory": request.trajectory,
            "topology": request.topology,
            **{f"processed.{key}": ref for key, ref in parent.output_artifacts.items()},
        }
        if request.reference_structure is not None:
            refs["reference_structure"] = request.reference_structure
        if request.atom_masses is not None:
            refs["atom_masses"] = request.atom_masses
        return {key: ref.sha256 or "" for key, ref in refs.items()}

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> TrajectoryAnalysisResult:
        parent = _one(invocation.inputs, "preprocessing", TrajectoryProcessingResult)
        plan_values = invocation.inputs.get("analysis_plan", ())
        request = (
            _one(invocation.inputs, "analysis_plan", TrajectoryAnalysisPlan).bind(parent)
            if plan_values
            else _one(invocation.inputs, "request", TrajectoryAnalysisRequest)
        )
        blockers = [
            issue
            for issue in self.engine.validate_request(request, parent)
            if issue.severity.blocks_execution
        ]
        if blockers:
            raise StageExecutionFailure(blockers[0].code, blockers[0].message)

        work = self.services.run_root / f"trajectory-analysis-{new_ulid()}"
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
        refs = {
            str(request.trajectory.artifact_id): request.trajectory,
            str(request.topology.artifact_id): request.topology,
        }
        for artifact in (request.reference_structure, request.atom_masses):
            if artifact is not None:
                refs[str(artifact.artifact_id)] = artifact
        format_by_id = {
            str(request.trajectory.artifact_id): request.trajectory_format,
            str(request.topology.artifact_id): request.topology_format,
        }
        if request.reference_structure is not None:
            format_by_id[str(request.reference_structure.artifact_id)] = request.topology_format
        if request.atom_masses is not None:
            format_by_id[str(request.atom_masses.artifact_id)] = "JSON"
        staged: dict[str, Path] = {}
        for artifact_id, artifact in refs.items():
            digest = artifact.sha256
            if digest is None or not self.services.artifacts.verify(digest):
                raise StageExecutionFailure(
                    "MD.ANALYSIS_ARTIFACT_INVALID",
                    f"input artifact {artifact.role!r} is missing or has an invalid hash",
                )
            suffix = format_by_id[artifact_id].casefold()
            if not suffix.isalnum():
                raise StageExecutionFailure(
                    "MD.ANALYSIS_FORMAT_INVALID", "request contains an unsafe file format"
                )
            relative = f"inputs/{artifact_id}.{suffix}"
            destination = _confined(work, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.services.artifacts.path_for(digest), destination)
            staged[artifact_id] = destination

        parameters = self.settings.model_dump(mode="json")
        worker_request = self.engine.worker_request(
            request,
            parent,
            self.settings,
            {
                artifact_id: path.relative_to(work).as_posix()
                for artifact_id, path in staged.items()
            },
        )
        request_path = _confined(work, self.settings.request_path)
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(worker_request, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        plan = self.engine.plan_request(
            request, parent, parameters=parameters, staged_inputs=staged, working_directory=work
        )
        outputs = execute_adapter_plan(
            self.services,
            plan,
            work,
            timeout_seconds=self.settings.timeout_seconds,
            artifact_kind="trajectory_analysis_output",
            error_prefix="MD.ANALYSIS",
        )

        result_rel = f"{self.settings.output_dir}/result.json"
        commands_rel = f"{self.settings.output_dir}/commands.json"
        raw = _read_json(_confined(work, result_rel))
        entries = raw.get("metrics")
        if not isinstance(entries, list):
            raise StageExecutionFailure(
                "MD.MDANALYSIS_METRICS_RESULT", "worker metrics field is not a list"
            )
        metric_refs: dict[str, ArtifactRef] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise StageExecutionFailure(
                    "MD.MDANALYSIS_METRICS_RESULT", "worker metric receipt is malformed"
                )
            name, filename = entry.get("name"), entry.get("file")
            if not isinstance(name, str) or not isinstance(filename, str):
                raise StageExecutionFailure(
                    "MD.MDANALYSIS_METRICS_RESULT", "worker metric name/path is invalid"
                )
            ref = outputs.get(f"{self.settings.output_dir}/{filename}")
            if ref is None:
                raise StageExecutionFailure(
                    "MD.MDANALYSIS_METRICS_RESULT",
                    f"planned output for metric {name!r} is missing",
                )
            metric_refs[name] = ref
        raw_ref, log_ref = outputs.get(result_rel), outputs.get(commands_rel)
        if raw_ref is None or log_ref is None:
            raise StageExecutionFailure(
                "MD.MDANALYSIS_METRICS_RESULT", "raw result or commands log was not registered"
            )
        sources = {"trajectory": request.trajectory, "topology": request.topology}
        if request.reference_structure is not None:
            sources["reference_structure"] = request.reference_structure
        if request.atom_masses is not None:
            sources["atom_masses"] = request.atom_masses
        return self.engine.normalize_result(
            request,
            parent,
            raw,
            metric_artifacts=metric_refs,
            raw_result_artifact=raw_ref,
            source_artifacts=sources,
            log_artifacts={"commands": log_ref},
        )


class TrajectoryAnalysisStagePlugin:
    plugin_id = "caddsuite.stage_handlers.mdanalysis"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        preprocessing = CapabilityInput(
            name="preprocessing",
            contracts=(TrajectoryProcessingResult.schema_id(),),
        )
        bound_request = StageCapability(
            kind="trajectory.analyze",
            engine="mdanalysis",
            inputs=(
                CapabilityInput(name="request", contracts=(TrajectoryAnalysisRequest.schema_id(),)),
                preprocessing,
            ),
            outputs=(TrajectoryAnalysisResult.schema_id(),),
        )
        analysis_plan = StageCapability(
            kind="trajectory.analyze_processed",
            engine="mdanalysis",
            inputs=(
                CapabilityInput(
                    name="analysis_plan", contracts=(TrajectoryAnalysisPlan.schema_id(),)
                ),
                preprocessing,
            ),
            outputs=(TrajectoryAnalysisResult.schema_id(),),
        )
        return tuple(
            StageHandlerRegistration(capability, self._build, self._preflight)
            for capability in (bound_request, analysis_plan)
        )

    @staticmethod
    def _settings(stage: StageDefinition) -> MDAnalysisMetricsParameters:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping):
            raise ValueError("MDAnalysis stage requires engine_parameters")
        return MDAnalysisMetricsParameters.model_validate(dict(raw))

    @classmethod
    def _preflight(cls, stage: StageDefinition) -> EnginePreflightResult:
        try:
            settings = cls._settings(stage)
            python = Path(settings.python_executable).expanduser().resolve(strict=True)
            worker = Path(settings.worker_script).expanduser().resolve(strict=True)
            if not python.is_file() or not os.access(python, os.X_OK) or not worker.is_file():
                raise ValueError("configured MDAnalysis interpreter or worker is unavailable")
            probe = subprocess.run(  # noqa: S603 - configured interpreter, fixed probe code
                [
                    str(python),
                    "-c",
                    "import importlib.metadata; print(importlib.metadata.version('MDAnalysis'))",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return EnginePreflightResult("unavailable", reason=f"MDAnalysis probe failed: {exc}")
        version = probe.stdout.strip()
        if probe.returncode or not version:
            return EnginePreflightResult(
                "unavailable",
                reason=(probe.stderr.strip() or "MDAnalysis version probe failed")[-2000:],
            )
        return EnginePreflightResult("available", engine_version=version)

    @classmethod
    def _build(cls, stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        settings = cls._settings(stage)
        python = Path(settings.python_executable).expanduser().resolve(strict=True)
        worker = Path(settings.worker_script).expanduser().resolve(strict=True)
        probe = subprocess.run(  # noqa: S603 - configured interpreter, fixed probe code
            [
                str(python),
                "-c",
                "import importlib.metadata; print(importlib.metadata.version('MDAnalysis'))",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            shell=False,
        )
        version = probe.stdout.strip()
        if not version:
            raise ValueError("MDAnalysis version probe returned no version")
        settings = settings.model_copy(
            update={"python_executable": str(python), "worker_script": str(worker)}
        )
        environment = capture_conda_environment(python.parent.parent, services)
        return MDAnalysisStageHandler(
            settings,
            engine_version=version,
            software_environment=environment,
            services=services,
        )


def plugin_factory() -> TrajectoryAnalysisStagePlugin:
    return TrajectoryAnalysisStagePlugin()


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "MD.ANALYSIS_INPUT_INVALID", f"input {name!r} requires one {expected.__name__}"
        )
    return values[0]


def _confined(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise StageExecutionFailure("MD.ANALYSIS_PATH_INVALID", "unsafe adapter output path")
    path = (root / Path(*pure.parts)).resolve(strict=False)
    if not path.is_relative_to(root.resolve(strict=True)):
        raise StageExecutionFailure(
            "MD.ANALYSIS_PATH_INVALID", "adapter path escaped work directory"
        )
    return path


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageExecutionFailure(
            "MD.ANALYSIS_RESULT_INVALID", f"worker result is unreadable: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise StageExecutionFailure("MD.ANALYSIS_RESULT_INVALID", "worker result must be an object")
    return value
