"""Discovered workflow stage wrapping the isolated AmberTools system-builder handler."""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TypeVar

from pydantic import Field

from caddsuite.adapters.system_builders.amber_handler import AmberTLeapBuilderHandler
from caddsuite.adapters.system_builders.amber_tleap import AmberTLeapBuilderAdapter
from caddsuite.application.environment import capture_conda_environment
from caddsuite.application.handlers import EnginePreflightResult, StageHandlerRegistration
from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ContractModel, VersionedContract
from caddsuite.contracts.complex import Complex
from caddsuite.contracts.execution import ResourceRequest, SoftwareEnvironment
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.contracts.system_plan import SystemBuildPlan
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.definition import StageDefinition
from caddsuite.workflow.scheduler import StageExecutionFailure, StageHandler, TaskInvocation

C = TypeVar("C", bound=VersionedContract)


class AmberTLeapSettings(ContractModel):
    """Explicit local paths and resource request for AmberTools/ParmEd."""

    amber_prefix: Path
    gromacs_executable: Path
    worker_script: Path | None = None
    memory_MiB: int = Field(ge=1)
    cpu_cores: int = Field(ge=1)


class AmberTLeapSystemBuildStageHandler:
    """Bind runtime identity to the plan, then delegate execution to the existing handler."""

    adapter_id = AmberTLeapBuilderAdapter.adapter_id
    adapter_version = AmberTLeapBuilderAdapter.version

    def __init__(
        self,
        delegate: AmberTLeapBuilderHandler,
        *,
        memory_MiB: int,
        cpu_cores: int,
        software_environment: SoftwareEnvironment | None = None,
    ) -> None:
        self.delegate = delegate
        self.memory_MiB = memory_MiB
        self.cpu_cores = cpu_cores
        self.engine_version = delegate.engine_version
        self.software_environment = software_environment

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        del scope
        if isinstance(value, Complex):
            return str(value.id)
        if isinstance(value, SystemBuildPlan):
            return hashlib.sha256(value.model_dump_json().encode()).hexdigest()
        raise TypeError(f"AmberTools stage cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        plan = _one(inputs, "plan", SystemBuildPlan)
        complex_model = _one(inputs, "complex", Complex)
        hashes = {f"source:{name}": ref.sha256 or "" for name, ref in plan.source_artifacts.items()}
        hashes["plan"] = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        hashes["complex"] = hashlib.sha256(complex_model.model_dump_json().encode()).hexdigest()
        return hashes

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        del inputs
        return (
            {"system_build.mode": "build", "system_build.adapter": self.adapter_id},
            frozenset({"system_build.mode", "system_build.adapter"}),
        )

    def resource_request(self, invocation: TaskInvocation) -> ResourceRequest:
        del invocation
        return ResourceRequest(memory_MiB=self.memory_MiB, cpu_cores=self.cpu_cores)

    def execute(self, invocation: TaskInvocation) -> SystemBuildResult:
        plan = _one(invocation.inputs, "plan", SystemBuildPlan)
        complex_model = _one(invocation.inputs, "complex", Complex)
        if plan.mode != "build":
            raise StageExecutionFailure(
                "AMBER_BUILD.MODE_MISMATCH",
                "AmberTools stage requires SystemBuildPlan mode='build'",
            )
        if plan.source_artifacts:
            raise StageExecutionFailure(
                "AMBER_BUILD.SOURCES_MUST_FOLLOW_COMPLEX",
                "AmberTools inputs are taken from the linked Complex protein and ligand artifacts",
            )
        protein_path = plan.parameters.get("protein_artifact_path")
        ligand_path = plan.parameters.get("ligand_artifact_path")
        if not isinstance(protein_path, str) or not isinstance(ligand_path, str):
            raise StageExecutionFailure(
                "AMBER_BUILD.INPUT_PATHS_REQUIRED",
                "AmberTools plan parameters must explicitly name protein and ligand artifact paths",
            )
        paths = (PurePosixPath(protein_path), PurePosixPath(ligand_path))
        if any(
            path.is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in path.parts)
            for value, path in zip((protein_path, ligand_path), paths, strict=True)
        ):
            raise StageExecutionFailure(
                "AMBER_BUILD.UNSAFE_PATH", "input paths must be confined relative paths"
            )
        if protein_path == ligand_path:
            raise StageExecutionFailure(
                "AMBER_BUILD.INPUT_PATH_COLLISION", "protein and ligand paths must differ"
            )
        try:
            request = plan.bind(
                complex_model,
                source_artifacts={
                    protein_path: complex_model.protein,
                    ligand_path: complex_model.ligand,
                },
            )
        except ValueError as exc:
            raise StageExecutionFailure("AMBER_BUILD.PLAN_BINDING_FAILED", str(exc)) from exc
        if request.mode != "build":
            raise StageExecutionFailure(
                "AMBER_BUILD.MODE_MISMATCH", "bound request must use build mode"
            )
        rebound = TaskInvocation(
            task=invocation.task,
            subject_id=invocation.subject_id,
            inputs={"request": (request,), "complex": (complex_model,)},
            decisions=invocation.decisions,
            run_id=invocation.run_id,
        )
        result = self.delegate.execute(rebound)
        if result.complex_id != complex_model.id or result.request_id != request.id:
            raise StageExecutionFailure(
                "AMBER_BUILD.LINEAGE_MISMATCH",
                "AmberTools result lost request or Complex identity",
            )
        return result


class AmberTLeapStagePlugin:
    plugin_id = "caddsuite.stage_handlers.amber_tleap"
    version = "0.1.0"

    @staticmethod
    def _settings(stage: StageDefinition) -> AmberTLeapSettings:
        raw = stage.params.get("engine_parameters")
        if not isinstance(raw, Mapping):
            raise ValueError("AmberTools stage requires engine_parameters")
        settings = AmberTLeapSettings.model_validate(dict(raw))
        prefix = settings.amber_prefix.expanduser().resolve(strict=True)
        gromacs = settings.gromacs_executable.expanduser().resolve(strict=True)
        worker = (
            settings.worker_script.expanduser().resolve(strict=True)
            if settings.worker_script is not None
            else Path(__file__).resolve().parents[2] / "caddsuite_worker" / "amber_tleap_worker.py"
        )
        worker = worker.resolve(strict=True)
        python = prefix / "bin" / "python"
        required = (
            python,
            prefix / "bin" / "tleap",
            prefix / "bin" / "antechamber",
            prefix / "bin" / "parmchk2",
            prefix / "bin" / "sander",
            gromacs,
            worker,
        )
        if not all(path.is_file() for path in required):
            missing = [str(path) for path in required if not path.is_file()]
            raise ValueError(f"AmberTools/GROMACS files are missing: {missing}")
        if not all(os.access(path, os.X_OK) for path in required[:-1]):
            raise ValueError("configured AmberTools and GROMACS executables must be executable")
        return settings.model_copy(
            update={
                "amber_prefix": prefix,
                "gromacs_executable": gromacs,
                "worker_script": worker,
            }
        )

    @classmethod
    def _preflight(cls, stage: StageDefinition) -> EnginePreflightResult:
        try:
            settings = cls._settings(stage)
            prefix = settings.amber_prefix
            python = prefix / "bin" / "python"
            gromacs = settings.gromacs_executable
            probe = subprocess.run(  # noqa: S603 - configured interpreter, fixed version probe
                [str(python), "-c", "import parmed; print(parmed.__version__)"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
            if probe.returncode != 0 or not probe.stdout.strip():
                return EnginePreflightResult(
                    "unavailable",
                    reason=(probe.stderr.strip() or "ParmEd import/version probe failed")[-2000:],
                )
            gmx_probe = subprocess.run(  # noqa: S603 - configured executable, fixed version argv
                [str(gromacs), "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                shell=False,
            )
            if gmx_probe.returncode != 0 or not (
                gmx_probe.stdout.strip() or gmx_probe.stderr.strip()
            ):
                return EnginePreflightResult(
                    "unavailable",
                    reason=(gmx_probe.stderr.strip() or "GROMACS version probe failed")[-2000:],
                )
            gmx_version = (gmx_probe.stdout.strip() or gmx_probe.stderr.strip()).splitlines()[0]
            return EnginePreflightResult(
                "available",
                engine_version=(
                    f"AmberTools prefix={prefix.name}; ParmEd {probe.stdout.strip()}; {gmx_version}"
                ),
            )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            return EnginePreflightResult(
                "unavailable", reason=f"AmberTools preflight failed: {exc}"
            )

    @classmethod
    def _build(cls, stage: StageDefinition, services: LocalRuntimeServices) -> StageHandler:
        settings = cls._settings(stage)
        worker_script = settings.worker_script
        if worker_script is None:
            raise ValueError("AmberTools worker script could not be resolved")
        adapter = AmberTLeapBuilderAdapter(
            amber_prefix=settings.amber_prefix,
            gromacs_executable=settings.gromacs_executable,
            worker_script=worker_script,
        )
        gmx_probe = subprocess.run(  # noqa: S603 - configured executable, fixed version argv
            [str(settings.gromacs_executable), "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            shell=False,
        )
        version = gmx_probe.stdout.strip() or gmx_probe.stderr.strip()
        delegate = AmberTLeapBuilderHandler(
            adapter=adapter,
            work_root=services.run_root / "system_build" / "amber",
            log_root=services.run_root / "logs" / "system_build" / "amber",
            engine_version=(
                f"AmberTools prefix={settings.amber_prefix.name}; {version.splitlines()[0]}"
            ),
            executor=services.executor,
            artifact_store=services.artifacts,
            sessions=services.sessions,
        )
        environment = capture_conda_environment(settings.amber_prefix, services)
        return AmberTLeapSystemBuildStageHandler(
            delegate,
            memory_MiB=settings.memory_MiB,
            cpu_cores=settings.cpu_cores,
            software_environment=environment,
        )

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        capability = StageCapability(
            kind="system_build",
            engine="amber_tleap",
            inputs=(
                CapabilityInput(name="complex", contracts=(Complex.schema_id(),)),
                CapabilityInput(name="plan", contracts=(SystemBuildPlan.schema_id(),)),
            ),
            outputs=(SystemBuildResult.schema_id(),),
            for_each=("pose",),
            iteration_contracts={"pose": (Complex.schema_id(),)},
            fanout_anchor={"pose": "complex"},
        )
        return (StageHandlerRegistration(capability, self._build, self._preflight),)


def _one(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, expected: type[C]) -> C:
    values = inputs.get(name, ())
    if len(values) != 1 or not isinstance(values[0], expected):
        raise StageExecutionFailure(
            "AMBER_BUILD.INPUT_CONTRACT_INVALID",
            f"port {name!r} requires exactly one {expected.__name__}",
        )
    return values[0]


def plugin_factory() -> AmberTLeapStagePlugin:
    return AmberTLeapStagePlugin()
