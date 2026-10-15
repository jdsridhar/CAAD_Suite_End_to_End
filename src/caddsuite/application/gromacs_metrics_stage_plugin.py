"""Discovered stages for GROMACS SASA and protein hydrogen-bond metrics."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from caddsuite.adapters.analysis.gromacs_hbond import (
    GromacsHbondAdapter,
    GromacsHbondParameters,
)
from caddsuite.adapters.analysis.gromacs_sasa import GromacsSasaAdapter, GromacsSasaParameters
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.planned_stage_runtime import confined_output, execute_adapter_plan
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
Settings = GromacsSasaParameters | GromacsHbondParameters
_ERROR = "MD.GROMACS_METRICS"


class GromacsMetricsStageHandler:
    """Stage verified XTC/TPR/index inputs and retain every declared engine output."""

    adapter_version = "0.1.0"
    engine_name = "GROMACS"

    def __init__(
        self,
        settings: Settings,
        *,
        engine_version: str,
        software_environment: SoftwareEnvironment | None,
        services: LocalRuntimeServices,
    ) -> None:
        self.settings = settings
        self.engine = (
            GromacsSasaAdapter()
            if isinstance(settings, GromacsSasaParameters)
            else GromacsHbondAdapter()
        )
        self.adapter_id = self.engine.adapter_id
        self.engine_version = engine_version
        self.software_environment = software_environment
        self.services = services

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if not isinstance(value, TrajectoryAnalysisPlan):
            raise TypeError("GROMACS metrics fan-out requires TrajectoryAnalysisPlan")
        return str(value.simulation_id)

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        plan = _one(inputs, "analysis_plan", TrajectoryAnalysisPlan)
        parent = _one(inputs, "preprocessing", TrajectoryProcessingResult)
        # Parent metadata also determines lineage, dimensions, windows and PBC treatment.
        return {
            "plan": _contract_hash(plan),
            "preprocessing": _contract_hash(parent),
            **{f"source.{key}": ref.sha256 or "" for key, ref in parent.source_artifacts.items()},
            **{
                f"processed.{key}": ref.sha256 or "" for key, ref in parent.output_artifacts.items()
            },
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> TrajectoryAnalysisResult:
        parent = _one(invocation.inputs, "preprocessing", TrajectoryProcessingResult)
        analysis_plan = _one(invocation.inputs, "analysis_plan", TrajectoryAnalysisPlan)
        request = _bind_request(analysis_plan, parent)
        blockers = [
            issue
            for issue in self.engine.validate_request(request, parent)
            if issue.severity.blocks_execution
        ]
        if blockers:
            raise StageExecutionFailure(blockers[0].code, blockers[0].message)

        work = self.services.run_root / f"gromacs-metrics-{new_ulid()}"
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
        sources = {"trajectory": request.trajectory, "topology": request.topology}
        if request.index_file is None:
            raise StageExecutionFailure(f"{_ERROR}.INPUT_INVALID", "source index is missing")
        sources["index"] = request.index_file
        formats = {"trajectory": request.trajectory_format, "topology": "TPR", "index": "NDX"}
        staged: dict[str, Path] = {}
        for key, artifact in sources.items():
            digest = artifact.sha256
            if digest is None or not self.services.artifacts.verify(digest):
                raise StageExecutionFailure(
                    f"{_ERROR}.ARTIFACT_INVALID",
                    f"input artifact {key!r} is missing or has an invalid hash",
                )
            suffix = formats[key].casefold()
            if not suffix.isalnum():
                raise StageExecutionFailure(f"{_ERROR}.FORMAT_INVALID", "unsafe input format")
            destination = confined_output(work, f"inputs/{artifact.artifact_id}.{suffix}", _ERROR)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.services.artifacts.path_for(digest), destination)
            staged[str(artifact.artifact_id)] = destination

        parameters = self.settings.model_dump(mode="json")
        try:
            # H-bond planning checks that request_path does not yet exist.
            plan = self.engine.plan_request(
                request, parent, parameters=parameters, staged_inputs=staged, working_directory=work
            )
            if isinstance(self.settings, GromacsSasaParameters):
                payload = GromacsSasaAdapter().worker_request(
                    request,
                    parent,
                    self.settings,
                    {key: path.relative_to(work).as_posix() for key, path in staged.items()},
                )
            else:
                payload = GromacsHbondAdapter().worker_request(
                    request,
                    parent,
                    self.settings,
                    {key: path.relative_to(work).as_posix() for key, path in staged.items()},
                )
        except ValueError as exc:
            raise StageExecutionFailure(f"{_ERROR}.PLAN_INVALID", str(exc)) from exc
        request_path = confined_output(work, self.settings.request_path, _ERROR)
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(payload, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        outputs = execute_adapter_plan(
            self.services,
            plan,
            work,
            timeout_seconds=self.settings.timeout_seconds,
            artifact_kind="trajectory_analysis_output",
            error_prefix=_ERROR,
        )

        def output(filename: str) -> ArtifactRef:
            relative = f"{self.settings.output_dir}/{filename}"
            ref = outputs.get(relative)
            if ref is None:
                raise StageExecutionFailure(
                    f"{_ERROR}.RESULT_INVALID", f"planned output is missing: {relative}"
                )
            return ref

        result_relative = f"{self.settings.output_dir}/result.json"
        try:
            raw = json.loads(
                confined_output(work, result_relative, _ERROR).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise StageExecutionFailure(f"{_ERROR}.RESULT_INVALID", str(exc)) from exc
        if not isinstance(raw, dict):
            raise StageExecutionFailure(
                f"{_ERROR}.RESULT_INVALID", "worker result must be an object"
            )

        if isinstance(self.settings, GromacsSasaParameters):
            metrics = {"sasa": output("sasa.csv")}
            engine_artifacts = {"sasa_xvg": output("sasa.xvg")}
            for name in ("surface", "sasa_output"):
                engine_artifacts[f"{name}_selection_index"] = output(f"{name}.ndx")
                engine_artifacts[f"{name}_selection_count"] = output(f"{name}.count.xvg")
        else:
            metrics = {"hbond_count": output("hbond_count.csv")}
            engine_artifacts = {"hbond_xvg": output("hbond_count.xvg")}
        logs = {"commands": output("commands.json")}
        for relative, ref in outputs.items():
            if relative.endswith((".stdout.txt", ".stderr.txt")):
                logs[relative.removeprefix(f"{self.settings.output_dir}/")] = ref
        try:
            return self.engine.normalize_result(
                request,
                parent,
                raw,
                metric_artifacts=metrics,
                raw_result_artifact=output("result.json"),
                source_artifacts=sources,
                log_artifacts=logs,
                engine_artifacts=engine_artifacts,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise StageExecutionFailure(f"{_ERROR}.RESULT_INVALID", str(exc)) from exc


class GromacsMetricsStagePlugin:
    plugin_id = "caddsuite.stage_handlers.gromacs_metrics"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        return tuple(
            StageHandlerRegistration(
                StageCapability(
                    kind="trajectory.analyze_processed",
                    engine=engine,
                    inputs=(
                        CapabilityInput(
                            name="analysis_plan", contracts=(TrajectoryAnalysisPlan.schema_id(),)
                        ),
                        CapabilityInput(
                            name="preprocessing",
                            contracts=(TrajectoryProcessingResult.schema_id(),),
                        ),
                    ),
                    outputs=(TrajectoryAnalysisResult.schema_id(),),
                ),
                self._build,
                self._preflight,
            )
            for engine in ("gromacs_sasa", "gromacs_hbond")
        )

    @staticmethod
    def _settings(stage: StageDefinition) -> Settings:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise ValueError("GROMACS metrics stage requires engine_parameters")
        if stage.engine == "gromacs_sasa":
            return GromacsSasaParameters.model_validate(dict(raw))
        if stage.engine == "gromacs_hbond":
            return GromacsHbondParameters.model_validate(dict(raw))
        raise ValueError(f"unsupported GROMACS metrics engine: {stage.engine!r}")

    @classmethod
    def _preflight(cls, stage: StageDefinition) -> EnginePreflightResult:
        try:
            settings = _resolve_settings(cls._settings(stage))
            probe = _version_probe(settings)
            worker = subprocess.run(  # noqa: S603 - configured interpreter, fixed help argv
                [settings.python_executable, settings.worker_script, "--help"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return EnginePreflightResult("unavailable", reason=f"GROMACS metrics preflight: {exc}")
        version = probe.stdout.strip() or probe.stderr.strip()
        if probe.returncode or not version or worker.returncode:
            return EnginePreflightResult(
                "unavailable",
                reason=(probe.stderr.strip() or worker.stderr.strip() or "GROMACS probe failed")[
                    -2000:
                ],
            )
        return EnginePreflightResult("available", engine_version=version)

    @classmethod
    def _build(cls, stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        settings = _resolve_settings(cls._settings(stage))
        probe = _version_probe(settings)
        version = probe.stdout.strip() or probe.stderr.strip()
        if probe.returncode or not version:
            raise ValueError("GROMACS version probe failed")
        # Keep the venv prefix, including when bin/python is a symlink.
        environment = capture_conda_environment(
            Path(settings.python_executable).parent.parent, services
        )
        return GromacsMetricsStageHandler(
            settings, engine_version=version, software_environment=environment, services=services
        )


def plugin_factory() -> GromacsMetricsStagePlugin:
    return GromacsMetricsStagePlugin()


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            f"{_ERROR}.INPUT_INVALID", f"input {name!r} requires one {expected.__name__}"
        )
    return values[0]


def _contract_hash(value: VersionedContract) -> str:
    serialized = json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _bind_request(
    plan: TrajectoryAnalysisPlan, parent: TrajectoryProcessingResult
) -> TrajectoryAnalysisRequest:
    try:
        bound = plan.bind(parent)
        topology = parent.source_artifacts.get("topology")
        index = parent.source_artifacts.get("index")
        if topology is None or index is None:
            raise ValueError(
                "GROMACS metrics require parent source_artifacts topology TPR and index"
            )
        # bind() validates parent identity/window and returns its generated GRO reference.
        # Revalidate a new request using the original hash-linked TPR and static index.
        return TrajectoryAnalysisRequest.model_validate(
            {
                **bound.model_dump(),
                "topology": topology,
                "topology_format": "TPR",
                "index_file": index,
            }
        )
    except ValueError as exc:
        raise StageExecutionFailure(f"{_ERROR}.INPUT_INVALID", str(exc)) from exc


def _resolve_executable(value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        found = shutil.which(str(candidate))
        if found is None:
            raise ValueError(f"configured executable is unavailable: {value!r}")
        candidate = Path(found)
    # resolve() would dereference a venv Python symlink and lose its environment.
    candidate = candidate.absolute()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise ValueError(f"configured executable is unavailable: {value!r}")
    return str(candidate)


def _resolve_settings(settings: Settings) -> Settings:
    worker = Path(settings.worker_script).expanduser().resolve(strict=True)
    if not worker.is_file():
        raise ValueError("configured GROMACS metrics worker is unavailable")
    return settings.model_copy(
        update={
            "gmx_executable": _resolve_executable(settings.gmx_executable),
            "python_executable": _resolve_executable(settings.python_executable),
            "worker_script": str(worker),
        }
    )


def _version_probe(settings: Settings) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - configured binary, fixed version argv
        [settings.gmx_executable, "--version"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        shell=False,
    )
