"""OpenMM production-stage adapter for native Amber parameterized systems."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal, NoReturn

from pydantic import Field, StrictInt, field_validator, model_validator

from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, PositiveFloat
from caddsuite.contracts.md import MDStage, MDStageInput, MDStageKind
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.ports.adapters import AdapterContext, CommandStep, ExecutionPlan
from caddsuite.ports.md_engine import MDExecutionCapabilities, MDProgress
from caddsuite.validation import default_registry
from caddsuite.validation.force_field_profiles import (
    AMBER_TLEAP_NATIVE_PROFILE_ID,
    default_force_field_profiles,
)
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class OpenMMPlanError(ValueError):
    """The native Amber system or selected MD stage is unsupported by this adapter."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OpenMMStagePlanParameters(ContractModel):
    """Explicit isolated-worker inputs for a CPU OpenMM production stage."""

    stage_index: Annotated[int, Field(ge=0)]
    python_executable: NonEmptyStr
    worker_script: NonEmptyStr
    topology_path: NonEmptyStr
    coordinates_path: NonEmptyStr
    output_prefix: NonEmptyStr
    random_seed: Annotated[StrictInt, Field(ge=0)]
    friction_per_ps: PositiveFloat
    report_interval_steps: Annotated[int, Field(ge=1)]
    cpu_threads: Annotated[int, Field(ge=1)] = 1
    platform_name: Literal["CPU", "Reference"] = "CPU"

    @field_validator("topology_path", "coordinates_path")
    @classmethod
    def _confined_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            "\x00" in value
            or "\\" in value
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(f"input path must be a canonical relative path: {value!r}")
        return value

    @field_validator("output_prefix")
    @classmethod
    def _safe_output_prefix(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
            raise ValueError("output_prefix must be a safe filename stem")
        if value in {".", ".."}:
            raise ValueError("output_prefix cannot be a dot path")
        return value

    @model_validator(mode="after")
    def _paths_are_distinct(self) -> OpenMMStagePlanParameters:
        if self.topology_path == self.coordinates_path:
            raise ValueError("Amber topology and coordinates must be distinct inputs")
        return self


class OpenMMMDAdapter:
    """Translate the shared MD stage contract to a shell-free OpenMM worker invocation.

    This proof adapter intentionally covers a narrow, explicit combination: the native Amber
    prmtop/inpcrd profile, NVT-like Langevin production, CPU/Reference platforms, PME, and
    constrained hydrogen bonds. Other force fields, ensembles, and restart semantics fail closed.
    """

    adapter_id = "caddsuite.md.openmm"
    version = "0.1.0"
    capabilities = MDExecutionCapabilities(
        stage_kinds=(MDStageKind.PRODUCTION,),
        topology_formats=("Amber prmtop/inpcrd",),
        trajectory_formats=("DCD",),
        supports_cpu=True,
        supports_gpu=False,
        supports_checkpoint_restart=False,
        supports_segmented_production=False,
    )

    def validate_stage(self, context: AdapterContext) -> tuple[ValidationIssue, ...]:
        try:
            self._resolve(context)
        except OpenMMPlanError as exc:
            result = context.inputs.get("system_build")
            subject = SubjectRef(
                kind="md_system",
                id=str(result.system.id) if isinstance(result, SystemBuildResult) else None,
            )
            return (
                ValidationIssue(
                    code=exc.code,
                    severity=Severity.BLOCKER,
                    subject=subject,
                    message=str(exc),
                    remediation=(
                        "Resolve the reported OpenMM input or stage mismatch before execution.",
                    ),
                    rule_version="1",
                ),
            )
        return ()

    def plan_stage(self, context: AdapterContext) -> ExecutionPlan:
        _build, parameters, stage, stage_input = self._resolve(context)
        topology_ref = stage_input.artifacts["topology"]
        coordinates_ref = stage_input.artifacts["coordinates"]
        nonbonded = stage.nonbonded
        cutoff_nm = nonbonded["cutoff_nm"]
        ewald_error_tolerance = nonbonded["ewald_error_tolerance"]
        if stage.n_steps is None or stage.timestep_fs is None or stage.temperature_K is None:
            _fail(
                "MD.OPENMM_STAGE_SETTINGS_MISSING", "validated production settings are incomplete"
            )
        argv = (
            parameters.python_executable,
            parameters.worker_script,
            "--topology",
            parameters.topology_path,
            "--coordinates",
            parameters.coordinates_path,
            "--topology-sha256",
            _required_hash(topology_ref.sha256, "topology"),
            "--coordinates-sha256",
            _required_hash(coordinates_ref.sha256, "coordinates"),
            "--output-prefix",
            parameters.output_prefix,
            "--steps",
            str(stage.n_steps),
            "--timestep-fs",
            str(stage.timestep_fs),
            "--temperature-k",
            str(stage.temperature_K),
            "--friction-per-ps",
            str(parameters.friction_per_ps),
            "--cutoff-nm",
            str(cutoff_nm),
            "--ewald-error-tolerance",
            str(ewald_error_tolerance),
            "--random-seed",
            str(parameters.random_seed),
            "--report-interval-steps",
            str(parameters.report_interval_steps),
            "--cpu-threads",
            str(parameters.cpu_threads),
            "--platform",
            parameters.platform_name,
        )
        return ExecutionPlan(
            commands=(
                CommandStep(
                    argv=argv,
                    working_directory=context.working_directory,
                    environment={"PYTHONNOUSERSITE": "1"},
                ),
            ),
            expected_outputs=tuple(
                f"{parameters.output_prefix}.{extension}"
                for extension in ("dcd", "pdb", "csv", "result.json")
            ),
        )

    def stage_input_artifacts(self, context: AdapterContext) -> dict[str, ArtifactRef]:
        build, parameters, _stage, stage_input = self._resolve(context)
        bindings = dict(build.system.engine_inputs["openmm"])
        bindings[parameters.topology_path] = stage_input.artifacts["topology"]
        bindings[parameters.coordinates_path] = stage_input.artifacts["coordinates"]
        return bindings

    def validate_execution_step(
        self, context: AdapterContext, step_index: int, stdout: bytes, stderr: bytes
    ) -> tuple[ValidationIssue, ...]:
        del context, step_index, stdout, stderr
        return ()

    def progress(
        self,
        stage_log: bytes | str,
        *,
        total_steps: int,
        aggregate_log: bytes | str | None = None,
        tail_bytes: int = 4000,
    ) -> MDProgress | None:
        if total_steps < 1 or tail_bytes < 1:
            raise ValueError("total_steps and tail_bytes must be positive")
        for source_name, source in (("stage_log", stage_log), ("aggregate_log", aggregate_log)):
            if source is None:
                continue
            payload = (
                source if isinstance(source, bytes) else source.encode("utf-8", errors="replace")
            )
            text = payload[-tail_bytes:].decode("utf-8", errors="replace")
            for match in reversed(
                tuple(re.finditer(r"^CADD_PROGRESS\s+(\d+)\s*/\s*(\d+)\s*$", text, re.M))
            ):
                completed = int(match.group(1))
                reported_total = int(match.group(2))
                if reported_total != total_steps or completed > total_steps:
                    continue
                return MDProgress(
                    completed_steps=completed,
                    total_steps=total_steps,
                    fraction_completed=completed / total_steps,
                    source=source_name,
                )
        return None

    @staticmethod
    def _resolve(
        context: AdapterContext,
    ) -> tuple[SystemBuildResult, OpenMMStagePlanParameters, MDStage, MDStageInput]:
        build = context.inputs.get("system_build")
        if not isinstance(build, SystemBuildResult):
            _fail("MD.OPENMM_CONTEXT_INVALID", "input 'system_build' must be a SystemBuildResult")
        if build.protocol is None:
            _fail("MD.OPENMM_PROTOCOL_MISSING", "an explicit MDProtocol is required")
        profile_id = build.parameterization.compatibility_profile_id
        profile = default_force_field_profiles().get(profile_id) if profile_id else None
        if (
            profile is None
            or not profile.supported
            or profile.profile_id != AMBER_TLEAP_NATIVE_PROFILE_ID
            or profile.topology_format.casefold() != "amber"
        ):
            _fail(
                "MD.OPENMM_FORCE_FIELD_PROFILE_UNSUPPORTED",
                f"native Amber force-field profile {profile_id!r} is absent or disabled",
            )
        issues = default_registry().run(
            "system_build",
            {"parameterization": build.parameterization, "md_system": build.system},
        )
        blocker = next((issue for issue in issues if issue.severity.blocks_execution), None)
        if blocker is not None:
            _fail("MD.OPENMM_FORCE_FIELD_INCOMPATIBLE", blocker.message)
        if build.parameterization.ff_family.value != "amber":
            _fail(
                "MD.OPENMM_FORCE_FIELD_INCOMPATIBLE",
                "OpenMM adapter requires Amber-family parameters",
            )
        native_inputs = build.system.engine_inputs.get("amber")
        if not native_inputs:
            _fail("MD.OPENMM_ENGINE_INPUTS_MISSING", "MDSystem has no native Amber input mapping")
        try:
            parameters = OpenMMStagePlanParameters.model_validate(context.parameters["openmm"])
        except (KeyError, ValueError, TypeError) as exc:
            _fail("MD.OPENMM_PARAMETERS_INVALID", f"invalid OpenMM stage parameters: {exc}")
        stage_input = context.inputs.get("stage_input")
        if not isinstance(stage_input, MDStageInput):
            _fail("MD.OPENMM_STAGE_INPUT_MISSING", "input 'stage_input' must be an MDStageInput")
        if stage_input.system_id != build.system.id:
            _fail(
                "MD.OPENMM_STAGE_INPUT_SYSTEM_MISMATCH", "stage input belongs to another MDSystem"
            )
        if stage_input.stage_index != parameters.stage_index:
            _fail(
                "MD.OPENMM_STAGE_INPUT_INDEX_MISMATCH",
                "stage input belongs to another protocol stage",
            )
        if parameters.stage_index >= len(build.protocol.stages):
            _fail("MD.OPENMM_STAGE_INDEX_INVALID", "stage index is outside the selected MDProtocol")
        stage = build.protocol.stages[parameters.stage_index]
        if stage.kind is not MDStageKind.PRODUCTION:
            _fail(
                "MD.OPENMM_STAGE_UNSUPPORTED",
                "OpenMM proof adapter supports production stages only",
            )
        if (
            stage.integrator.casefold() != "langevin"
            or (stage.thermostat or "").casefold() != "langevin"
        ):
            _fail(
                "MD.OPENMM_INTEGRATOR_UNSUPPORTED",
                "select the supported Langevin production integrator",
            )
        if (
            stage.n_steps is None
            or stage.n_steps < 1
            or stage.timestep_fs is None
            or stage.timestep_fs > 2.0
            or stage.temperature_K is None
            or stage.constraints != "HBonds"
            or stage.hmr is not False
            or stage.pressure_bar is not None
            or stage.barostat is not None
        ):
            _fail(
                "MD.OPENMM_STAGE_SETTINGS_UNSUPPORTED",
                "OpenMM proof requires explicit <=2 fs production, temperature, HBonds, "
                "HMR=false, and no barostat",
            )
        nonbonded = stage.nonbonded
        if (
            nonbonded.get("method") != "PME"
            or not isinstance(nonbonded.get("cutoff_nm"), (int, float))
            or not isinstance(nonbonded.get("ewald_error_tolerance"), (int, float))
        ):
            _fail(
                "MD.OPENMM_NONBONDED_UNSUPPORTED",
                "OpenMM proof requires explicit PME, cutoff_nm, and ewald_error_tolerance settings",
            )
        topology_ref = stage_input.artifacts.get("topology")
        coordinates_ref = stage_input.artifacts.get("coordinates")
        source_refs = {**build.raw_artifacts, **build.normalized_artifacts, **native_inputs}
        for role, path, ref in (
            ("topology", parameters.topology_path, topology_ref),
            ("coordinates", parameters.coordinates_path, coordinates_ref),
        ):
            if path not in native_inputs:
                _fail("MD.OPENMM_INPUT_UNREGISTERED", f"Amber input {path!r} is not registered")
            registered = source_refs.get(path)
            if ref is None or ref.sha256 is None:
                _fail(
                    "MD.OPENMM_STAGE_ARTIFACT_MISSING", f"stage input lacks hashed {role} artifact"
                )
            if registered is None or registered.sha256 != ref.sha256:
                _fail(
                    "MD.OPENMM_STAGE_ARTIFACT_HASH_MISMATCH",
                    f"{role} differs from its registered Amber input",
                )
        return build, parameters, stage, stage_input


def _required_hash(value: str | None, role: str) -> str:
    if value is None:
        _fail("MD.OPENMM_STAGE_ARTIFACT_MISSING", f"{role} artifact has no SHA-256")
    return value


def _fail(code: str, message: str) -> NoReturn:
    raise OpenMMPlanError(code, message)
