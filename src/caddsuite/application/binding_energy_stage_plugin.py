"""Discovered MM/GBSA workflow stage backed by the reviewed GROMACS adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from caddsuite.adapters.binding_energy.gmx_mmpbsa import (
    GromacsMMPBSAAdapter,
    GromacsMMPBSAParameters,
)
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.planned_stage_runtime import confined_output, execute_adapter_plan
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.analysis import BindingEnergyRequest, BindingEnergyResult
from caddsuite.contracts.base import ArtifactRef, VersionedContract
from caddsuite.contracts.execution import SoftwareEnvironment
from caddsuite.domain.identity import new_ulid
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class GromacsMMPBSAStageHandler:
    """Run one hash-linked request using the existing strict engine adapter."""

    adapter_id = GromacsMMPBSAAdapter.adapter_id
    adapter_version = GromacsMMPBSAAdapter.version

    def __init__(
        self,
        settings: GromacsMMPBSAParameters,
        *,
        engine_version: str,
        software_environment: SoftwareEnvironment | None,
        services: LocalRuntimeServices,
    ) -> None:
        self.settings = settings
        self.engine = GromacsMMPBSAAdapter()
        self.engine_version = engine_version
        self.software_environment = software_environment
        self.services = services

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if not isinstance(value, BindingEnergyRequest):
            raise TypeError("binding-energy fan-out requires BindingEnergyRequest")
        return str(value.simulation.id)

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        request = _one(inputs, "request", BindingEnergyRequest)
        return {
            f"source.{path}": artifact.sha256 or ""
            for path, artifact in request.source_artifacts.items()
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> BindingEnergyResult:
        request = _one(invocation.inputs, "request", BindingEnergyRequest)
        blockers = [
            issue
            for issue in self.engine.validate_request(request)
            if issue.severity.blocks_execution
        ]
        if blockers:
            raise StageExecutionFailure(blockers[0].code, blockers[0].message)

        work = self.services.run_root / f"binding-energy-{new_ulid()}"
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
        staged: dict[str, Path] = {}
        source_refs: dict[str, ArtifactRef] = {}
        for relative, artifact in request.source_artifacts.items():
            digest = artifact.sha256
            if digest is None or not self.services.artifacts.verify(digest):
                raise StageExecutionFailure(
                    "BINDING_ENERGY.ARTIFACT_INVALID",
                    f"source artifact {relative!r} is missing or failed hash verification",
                )
            destination = confined_output(work, relative, "BINDING_ENERGY")
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(self.services.artifacts.path_for(digest), destination)
            staged[str(artifact.artifact_id)] = destination
            source_refs[relative] = artifact

        parameters = self.settings.model_dump(mode="json")
        try:
            plan = self.engine.plan_request(
                request,
                parameters=parameters,
                staged_inputs=staged,
                working_directory=work,
            )
            worker_request = self.engine.worker_request(
                request,
                parameters=self.settings,
                staged_inputs=staged,
                working_directory=work,
            )
            request_path = confined_output(work, self.settings.request_path, "BINDING_ENERGY")
            request_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            request_path.write_text(
                json.dumps(worker_request, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        except (OSError, ValueError, TypeError) as exc:
            raise StageExecutionFailure("BINDING_ENERGY.PREPARATION_FAILED", str(exc)) from exc

        outputs = execute_adapter_plan(
            self.services,
            plan,
            work,
            timeout_seconds=self.settings.timeout_seconds,
            artifact_kind="binding_energy_output",
            error_prefix="BINDING_ENERGY",
        )
        prefix = self.settings.output_dir
        result_relative = f"{prefix}/result.json"
        raw = _read_json(confined_output(work, result_relative, "BINDING_ENERGY"))
        dat_ref = outputs.get(f"{prefix}/FINAL_RESULTS_MMGBSA.dat")
        csv_ref = outputs.get(f"{prefix}/FINAL_RESULTS_MMGBSA.csv")
        if dat_ref is None or csv_ref is None:
            raise StageExecutionFailure(
                "BINDING_ENERGY.NATIVE_REPORT_MISSING",
                "worker completed without registered native .dat and .csv reports",
            )
        try:
            raw["dat_text"] = confined_output(
                work, f"{prefix}/FINAL_RESULTS_MMGBSA.dat", "BINDING_ENERGY"
            ).read_text(encoding="utf-8")
            raw["csv_text"] = confined_output(
                work, f"{prefix}/FINAL_RESULTS_MMGBSA.csv", "BINDING_ENERGY"
            ).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise StageExecutionFailure(
                "BINDING_ENERGY.NATIVE_REPORT_INVALID",
                f"native gmx_MMPBSA report could not be read: {exc}",
            ) from exc

        log_artifacts = {
            path: ref
            for path, ref in outputs.items()
            if path.endswith(".stdout.txt") or path.endswith(".stderr.txt")
        }
        command_ref = outputs.get(f"{prefix}/commands.json")
        if command_ref is not None:
            log_artifacts["commands"] = command_ref
        return self.engine.normalize_result(
            request,
            raw,
            source_artifacts=source_refs,
            output_artifacts=outputs,
            log_artifacts=log_artifacts,
        )


class GromacsMMPBSAStagePlugin:
    plugin_id = "caddsuite.stage_handlers.gmx_mmpbsa"
    version = "0.1.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="binding_energy",
            engine="gmx_mmpbsa",
            inputs=(
                CapabilityInput(name="request", contracts=(BindingEnergyRequest.schema_id(),)),
            ),
            outputs=(BindingEnergyResult.schema_id(),),
        )
        return (StageHandlerRegistration(capability, self._build, self._preflight),)

    @staticmethod
    def _settings(stage: StageDefinition) -> GromacsMMPBSAParameters:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
            raise ValueError("gmx_MMPBSA stage requires engine_parameters")
        return GromacsMMPBSAParameters.model_validate(dict(raw))

    @classmethod
    def _resolve_settings(cls, stage: StageDefinition) -> tuple[GromacsMMPBSAParameters, str]:
        settings = cls._settings(stage)
        gmx = _resolve_executable(settings.gmx_executable)
        executable = _resolve_executable(settings.gmx_mmpbsa_executable)
        python = _resolve_executable(settings.python_executable)
        mpi = (
            _resolve_executable(settings.mpi_launcher)
            if settings.mpi_launcher is not None
            else None
        )
        worker = Path(settings.worker_script).expanduser().resolve(strict=True)
        if not worker.is_file():
            raise ValueError(f"configured worker script is unavailable: {worker}")
        settings = settings.model_copy(
            update={
                "gmx_executable": gmx,
                "gmx_mmpbsa_executable": executable,
                "python_executable": python,
                "mpi_launcher": mpi,
                "worker_script": str(worker),
            }
        )
        probe = subprocess.run(  # noqa: S603 - resolved configured executable, fixed argv
            [gmx, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            shell=False,
        )
        version = probe.stdout.strip() or probe.stderr.strip()
        if probe.returncode or not version:
            raise ValueError((probe.stderr.strip() or "GROMACS version probe failed")[-2000:])
        return settings, version

    @classmethod
    def _preflight(cls, stage: StageDefinition) -> EnginePreflightResult:
        try:
            settings, gmx_version = cls._resolve_settings(stage)
            probe = subprocess.run(  # noqa: S603 - resolved configured Python, fixed probe code
                [
                    settings.python_executable,
                    "-c",
                    "import importlib.util; "
                    "assert any(importlib.util.find_spec(name) for name in "
                    "('GMXMMPBSA', 'gmx_MMPBSA'))",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return EnginePreflightResult(
                "unavailable", reason=f"gmx_MMPBSA preflight failed: {exc}"
            )
        if probe.returncode:
            return EnginePreflightResult(
                "unavailable",
                reason=(probe.stderr.strip() or "gmx_MMPBSA module is unavailable")[-2000:],
            )
        return EnginePreflightResult(
            "available",
            engine_version=gmx_version,
            details={
                "worker_python": settings.python_executable,
                "gmx_mmpbsa_executable": settings.gmx_mmpbsa_executable,
                "mpi_launcher": settings.mpi_launcher,
                "mpi_processes": settings.mpi_processes,
            },
        )

    @classmethod
    def _build(cls, stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        settings, gmx_version = cls._resolve_settings(stage)
        environment = capture_conda_environment(
            Path(settings.python_executable).resolve().parent.parent, services
        )
        return GromacsMMPBSAStageHandler(
            settings,
            engine_version=gmx_version,
            software_environment=environment,
            services=services,
        )


def plugin_factory() -> GromacsMMPBSAStagePlugin:
    return GromacsMMPBSAStagePlugin()


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "BINDING_ENERGY.INPUT_INVALID",
            f"input {name!r} requires exactly one {expected.__name__}",
        )
    return values[0]


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageExecutionFailure(
            "BINDING_ENERGY.RESULT_INVALID", f"worker result is unreadable: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise StageExecutionFailure("BINDING_ENERGY.RESULT_INVALID", "result must be an object")
    return value


def _resolve_executable(value: str | None) -> str:
    if value is None:
        raise ValueError("optional executable path is not configured")
    candidate = Path(value).expanduser()
    resolved = (
        shutil.which(value) if not candidate.is_absolute() else str(candidate.resolve(strict=True))
    )
    if resolved is None or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"configured executable is unavailable: {value!r}")
    return resolved
