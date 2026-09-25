"""GROMACS MD-stage validation and shell-free command planning.

This module is an adapter. It reads normalized system/protocol contracts and translates one
requested stage into GROMACS-specific argv; workflow scheduling does not contain these flags.
"""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal, NoReturn

from pydantic import Field, StrictInt, field_validator, model_validator

from caddsuite.contracts.base import ContractModel, NonEmptyStr, PositiveFloat
from caddsuite.contracts.md import MDStage, MDStageInput, MDStageKind
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.ports.adapters import AdapterContext, CommandStep, ExecutionPlan
from caddsuite.ports.md_engine import MDExecutionCapabilities, MDProgress
from caddsuite.validation import default_registry
from caddsuite.validation.force_field_profiles import default_force_field_profiles
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class GromacsPlanError(ValueError):
    """A GROMACS stage is invalid or incompatible with its normalized MD system."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_GROMPP_WARNING = re.compile(
    r"^\s*(?:Warning:\s*(.*)|WARNING(?:\s+\d+)?(?:\s+\[[^]]+\])?:\s*(.*))$",
    re.IGNORECASE,
)
_GROMPP_NOTE = re.compile(r"^\s*NOTE\s+\d+\b", re.IGNORECASE)
_PROGRESS_STEP = re.compile(r"^\s*step\s+(\d+),\s*(.*)$", re.IGNORECASE)
_REMAINING_TIME = re.compile(
    r"remaining wall clock time:\s*([0-9]+(?:\.[0-9]+)?)\s*s\b", re.IGNORECASE
)
_FINISH_TIME = re.compile(r"will finish\s+(.+)$", re.IGNORECASE)


def normalize_index_final_newline(payload: bytes) -> tuple[bytes, bool]:
    """Append one LF only when an index file lacks a final newline.

    The source bytes remain the authoritative artifact. Callers should store the returned bytes
    as a separate derived artifact and record both hashes; group contents are not rewritten.
    """
    if payload.endswith(b"\n"):
        return payload, False
    return payload + b"\n", True


def classify_grompp_warnings(
    stdout: bytes | str, stderr: bytes | str
) -> tuple[ValidationIssue, ...]:
    """Capture GROMACS warning blocks and turn each into a blocking, actionable issue.

    GROMACS notes are intentionally ignored: they are informational text and do not have the
    same behavior as warnings. No warning is auto-accepted by this classifier.
    """
    stdout_text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout
    stderr_text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    lines = (stdout_text + "\n" + stderr_text).splitlines()
    messages: list[str] = []
    index = 0
    while index < len(lines):
        match = _GROMPP_WARNING.match(lines[index])
        if match is None:
            index += 1
            continue
        message = (match.group(1) or match.group(2) or "").strip()
        index += 1
        block = [message] if message else []
        if message.casefold().endswith("last line:") and index < len(lines):
            block.append(lines[index].strip())
            index += 1
        elif not message:
            while index < len(lines):
                continuation = lines[index]
                if (
                    not continuation.strip()
                    or _GROMPP_WARNING.match(continuation)
                    or _GROMPP_NOTE.match(continuation)
                ):
                    break
                block.append(continuation.strip())
                index += 1
        messages.append(" ".join(part for part in block if part))

    issues: list[ValidationIssue] = []
    for message in messages:
        is_newline = "file does not end with a newline" in message.casefold()
        issues.append(
            ValidationIssue(
                code=(
                    "MD.GROMACS_INDEX_FINAL_NEWLINE" if is_newline else "MD.GROMACS_WARNING_BLOCKED"
                ),
                severity=Severity.BLOCKER,
                subject=SubjectRef(kind="md_stage", label="grompp"),
                message=f"GROMACS grompp warning: {message or '(warning text not captured)'}",
                evidence={"warning": message},
                remediation=(
                    (
                        "Preserve and hash the original index file, then use a separate derived "
                        "copy with a final LF; do not alter atom-group membership."
                    )
                    if is_newline
                    else "Resolve this warning in the inputs or parameters, then rerun grompp; "
                    "do not suppress it with -maxwarn.",
                ),
                rule_version="1",
            )
        )
    return tuple(issues)


def parse_gromacs_progress(
    stage_log: bytes | str,
    *,
    total_steps: int,
    aggregate_log: bytes | str | None = None,
    tail_bytes: int = 4000,
) -> MDProgress | None:
    """Parse the latest GROMACS step/ETA line, falling back to the aggregate run log.

    `mdrun -v` progress is carriage-return separated. The legacy monitor also had to fall back
    to its unbuffered aggregate stdout log when the engine's own stage log lagged behind.
    """
    if total_steps < 1:
        raise ValueError("total_steps must be positive")
    if tail_bytes < 1:
        raise ValueError("tail_bytes must be positive")
    sources: tuple[tuple[Literal["stage_log", "aggregate_log"], bytes | str | None], ...] = (
        ("stage_log", stage_log),
        ("aggregate_log", aggregate_log),
    )
    for source_name, source in sources:
        if source is None:
            continue
        encoded = source if isinstance(source, bytes) else source.encode("utf-8", errors="replace")
        text = encoded[-tail_bytes:].decode("utf-8", errors="replace").replace("\r", "\n")
        lines = text.splitlines()
        for line in reversed(lines):
            match = _PROGRESS_STEP.match(line)
            if match is None:
                continue
            completed = int(match.group(1))
            if completed > total_steps:
                continue
            detail = match.group(2)
            finish_match = _FINISH_TIME.search(detail)
            remaining_match = _REMAINING_TIME.search(detail)
            return MDProgress(
                completed_steps=completed,
                total_steps=total_steps,
                fraction_completed=completed / total_steps,
                estimated_remaining_seconds=(
                    float(remaining_match.group(1)) if remaining_match is not None else None
                ),
                estimated_finish_text=(
                    finish_match.group(1).strip() if finish_match is not None else None
                ),
                source=source_name,
            )
    return None


class GromacsStagePlanParameters(ContractModel):
    """Explicit staged input paths and resource choices for one GROMACS stage.

    Paths are relative to the private stage working directory. The application handler is
    responsible for materializing each path from a hash-verified artifact before execution.
    """

    stage_index: Annotated[int, Field(ge=0)]
    executable: NonEmptyStr = "gmx"
    minimization_executable: NonEmptyStr | None = None
    mdp_path: NonEmptyStr | None = None
    coordinates_path: NonEmptyStr | None = None
    topology_path: NonEmptyStr
    index_path: NonEmptyStr | None = None
    reference_coordinates_path: NonEmptyStr | None = None
    previous_checkpoint_path: NonEmptyStr | None = None
    resume_checkpoint_path: NonEmptyStr | None = None
    output_prefix: NonEmptyStr
    segment_index: Annotated[int, Field(ge=1)] = 1
    target_ns: PositiveFloat | None = None
    resource_mode: Literal["cpu", "gpu"] = "cpu"
    cpu_threads: Annotated[int, Field(ge=1)] = 1
    gpu_ids: tuple[StrictInt, ...] = ()
    checkpoint_interval_minutes: PositiveFloat | None = None
    maximum_runtime_hours: PositiveFloat | None = None

    @field_validator(
        "mdp_path",
        "coordinates_path",
        "topology_path",
        "index_path",
        "reference_coordinates_path",
        "previous_checkpoint_path",
        "resume_checkpoint_path",
    )
    @classmethod
    def _relative_input_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
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
    def _basename_only(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
            raise ValueError("output_prefix must be a safe filename stem")
        if value in {".", ".."}:
            raise ValueError("output_prefix cannot be a dot path")
        return value

    @field_validator("executable", "minimization_executable")
    @classmethod
    def _safe_executable(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("executable cannot contain a NUL byte")
        return value

    @model_validator(mode="after")
    def _resource_and_checkpoint_choices(self) -> GromacsStagePlanParameters:
        if len(set(self.gpu_ids)) != len(self.gpu_ids) or any(i < 0 for i in self.gpu_ids):
            raise ValueError("gpu_ids must be unique non-negative device identifiers")
        if self.resource_mode == "gpu" and not self.gpu_ids:
            raise ValueError("GPU resource mode requires at least one explicit gpu_id")
        if self.resource_mode == "cpu" and self.gpu_ids:
            raise ValueError("gpu_ids cannot be selected in CPU resource mode")
        if self.resume_checkpoint_path is not None:
            expected = f"{self.output_prefix}.cpt"
            if self.resume_checkpoint_path != expected:
                raise ValueError(
                    "resume checkpoint must match the selected output prefix so GROMACS can "
                    "append to the same stage outputs"
                )
        return self


class GromacsMDAdapter:
    """Initial GROMACS implementation of the engine-independent MD planning port."""

    adapter_id = "caddsuite.md.gromacs"
    version = "0.1.0"
    capabilities = MDExecutionCapabilities(
        stage_kinds=tuple(MDStageKind),
        topology_formats=("GROMACS topology",),
        trajectory_formats=("XTC", "TRR"),
        supports_cpu=True,
        supports_gpu=True,
        supports_checkpoint_restart=True,
        supports_segmented_production=True,
    )

    def validate_stage(self, context: AdapterContext) -> tuple[ValidationIssue, ...]:
        try:
            self._resolve(context)
        except GromacsPlanError as exc:
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
                    remediation=("Resolve the reported input/profile mismatch before execution.",),
                    rule_version="1",
                ),
            )
        return ()

    def plan_stage(self, context: AdapterContext) -> ExecutionPlan:
        build, parameters, stage = self._resolve(context)
        del build
        commands: list[CommandStep] = []
        prefix = parameters.output_prefix
        if parameters.resume_checkpoint_path is None:
            if parameters.mdp_path is None or parameters.coordinates_path is None:
                _fail(
                    "MD.GROMACS_INPUT_MISSING",
                    "a fresh stage requires explicit MDP and coordinate paths",
                )
            argv = [
                parameters.executable,
                "grompp",
                "-f",
                parameters.mdp_path,
                "-o",
                f"{prefix}.tpr",
                "-c",
                parameters.coordinates_path,
                "-p",
                parameters.topology_path,
            ]
            if parameters.reference_coordinates_path is not None:
                argv.extend(("-r", parameters.reference_coordinates_path))
            if parameters.index_path is not None:
                argv.extend(("-n", parameters.index_path))
            if parameters.previous_checkpoint_path is not None:
                argv.extend(("-t", parameters.previous_checkpoint_path))
            # No -maxwarn: warning policy is handled explicitly in Phase 7.3.
            commands.append(
                CommandStep(
                    argv=tuple(argv),
                    working_directory=context.working_directory,
                    environment={},
                )
            )

        engine = parameters.executable
        if stage.kind is MDStageKind.MINIMIZATION and parameters.minimization_executable:
            engine = parameters.minimization_executable
        mdrun = [engine, "mdrun", "-v", "-deffnm", prefix]
        if parameters.resume_checkpoint_path is not None:
            mdrun.extend(("-cpi", parameters.resume_checkpoint_path, "-append"))
        if parameters.checkpoint_interval_minutes is not None:
            mdrun.extend(("-cpt", str(parameters.checkpoint_interval_minutes)))
        if parameters.maximum_runtime_hours is not None:
            mdrun.extend(("-maxh", str(parameters.maximum_runtime_hours)))
        mdrun.extend(("-ntomp", str(parameters.cpu_threads), "-pin", "on", "-pinoffset", "0"))
        environment = {"OMP_NUM_THREADS": str(parameters.cpu_threads)}
        if parameters.resource_mode == "gpu":
            mdrun.extend(("-nb", "gpu", "-bonded", "gpu", "-pme", "gpu", "-update", "gpu"))
            environment["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, parameters.gpu_ids))
        environment["OMP_WAIT_POLICY"] = "active"
        commands.append(
            CommandStep(
                argv=tuple(mdrun),
                working_directory=context.working_directory,
                environment=environment,
            )
        )
        expected = (f"{prefix}.tpr", f"{prefix}.gro", f"{prefix}.log")
        return ExecutionPlan(commands=tuple(commands), expected_outputs=expected)

    def progress(
        self,
        stage_log: bytes | str,
        *,
        total_steps: int,
        aggregate_log: bytes | str | None = None,
        tail_bytes: int = 4000,
    ) -> MDProgress | None:
        return parse_gromacs_progress(
            stage_log,
            total_steps=total_steps,
            aggregate_log=aggregate_log,
            tail_bytes=tail_bytes,
        )

    def _resolve(
        self, context: AdapterContext
    ) -> tuple[SystemBuildResult, GromacsStagePlanParameters, MDStage]:
        result = context.inputs.get("system_build")
        if not isinstance(result, SystemBuildResult):
            _fail("MD.GROMACS_CONTEXT_INVALID", "input 'system_build' must be a SystemBuildResult")
        if result.protocol is None:
            _fail(
                "MD.GROMACS_PROTOCOL_MISSING",
                "the normalized system build has no MDProtocol; select or import an explicit "
                "protocol before execution",
            )
        profile_id = result.parameterization.compatibility_profile_id
        profile = default_force_field_profiles().get(profile_id) if profile_id else None
        if (
            profile is None
            or not profile.supported
            or profile.topology_format.casefold() != "gromacs"
        ):
            _fail(
                "MD.GROMACS_FORCE_FIELD_PROFILE_UNSUPPORTED",
                f"force-field compatibility profile {profile_id!r} is absent or disabled for "
                "GROMACS execution",
            )
        ff_issues = default_registry().run(
            "system_build",
            {"parameterization": result.parameterization, "md_system": result.system},
        )
        blocking_ff = next((issue for issue in ff_issues if issue.severity.blocks_execution), None)
        if blocking_ff is not None:
            _fail(
                "MD.GROMACS_FORCE_FIELD_INCOMPATIBLE",
                f"force-field validation blocked execution: {blocking_ff.message}",
            )
        engine_inputs = result.system.engine_inputs.get("gromacs")
        if not engine_inputs:
            _fail(
                "MD.GROMACS_ENGINE_INPUTS_MISSING",
                "MDSystem has no GROMACS engine-input artifact mapping",
            )
        try:
            raw = context.parameters["gromacs"]
            parameters = GromacsStagePlanParameters.model_validate(raw)
        except (KeyError, ValueError, TypeError) as exc:
            _fail("MD.GROMACS_PARAMETERS_INVALID", f"invalid GROMACS stage parameters: {exc}")
        stage_input = context.inputs.get("stage_input")
        if not isinstance(stage_input, MDStageInput):
            _fail("MD.GROMACS_STAGE_INPUT_MISSING", "input 'stage_input' must be an MDStageInput")
        if stage_input.system_id != result.system.id:
            _fail(
                "MD.GROMACS_STAGE_INPUT_SYSTEM_MISMATCH",
                "stage input belongs to another MDSystem",
            )
        if stage_input.stage_index != parameters.stage_index:
            _fail(
                "MD.GROMACS_STAGE_INPUT_INDEX_MISMATCH",
                "stage input belongs to another protocol stage",
            )
        stages = result.protocol.stages
        if parameters.stage_index >= len(stages):
            _fail(
                "MD.GROMACS_STAGE_INDEX_INVALID",
                f"stage_index {parameters.stage_index} is outside protocol with "
                f"{len(stages)} stage(s)",
            )
        stage = stages[parameters.stage_index]
        if stage.kind not in self.capabilities.stage_kinds:
            _fail("MD.GROMACS_STAGE_UNSUPPORTED", f"GROMACS does not support {stage.kind.value}")
        if (
            stage.kind is MDStageKind.MINIMIZATION
            and parameters.resume_checkpoint_path is None
            and parameters.reference_coordinates_path is None
        ):
            _fail(
                "MD.GROMACS_REFERENCE_MISSING",
                "minimization requires an explicit reference-coordinate path",
            )
        if stage.kind is MDStageKind.PRODUCTION:
            self._validate_segment(stage, parameters)
        elif parameters.segment_index != 1 or parameters.previous_checkpoint_path is not None:
            _fail(
                "MD.GROMACS_SEGMENT_INVALID",
                "segment indexing and previous-segment checkpoints apply only to production stages",
            )
        if (
            parameters.resume_checkpoint_path is not None
            and not self.capabilities.supports_checkpoint_restart
        ):
            _fail("MD.GROMACS_RESTART_UNSUPPORTED", "adapter does not support checkpoint restart")
        if parameters.resource_mode == "gpu" and not self.capabilities.supports_gpu:
            _fail("MD.GROMACS_GPU_UNSUPPORTED", "adapter does not declare GPU execution support")
        if parameters.resource_mode == "cpu" and not self.capabilities.supports_cpu:
            _fail("MD.GROMACS_CPU_UNSUPPORTED", "adapter does not declare CPU execution support")

        if parameters.topology_path not in engine_inputs:
            _fail(
                "MD.GROMACS_INPUT_UNREGISTERED",
                f"topology input {parameters.topology_path!r} is not registered on the "
                "normalized GROMACS system",
            )
        bindings: list[tuple[str, str, bool]] = [("topology", parameters.topology_path, True)]
        if parameters.resume_checkpoint_path is None:
            if parameters.mdp_path is None or parameters.coordinates_path is None:
                _fail("MD.GROMACS_INPUT_MISSING", "a fresh stage requires MDP and coordinates")
            bindings.extend(
                (
                    ("md_parameters", parameters.mdp_path, False),
                    ("coordinates", parameters.coordinates_path, False),
                )
            )
            if parameters.index_path is not None:
                bindings.append(("index", parameters.index_path, False))
            if parameters.reference_coordinates_path is not None:
                bindings.append(
                    ("reference_coordinates", parameters.reference_coordinates_path, False)
                )
            if parameters.previous_checkpoint_path is not None:
                bindings.append(("previous_checkpoint", parameters.previous_checkpoint_path, False))
        else:
            bindings.extend(
                (
                    ("tpr", f"{parameters.output_prefix}.tpr", False),
                    ("resume_checkpoint", parameters.resume_checkpoint_path, False),
                )
            )
        source_refs = {
            **result.raw_artifacts,
            **result.normalized_artifacts,
            **engine_inputs,
        }
        for role, path, require_system_artifact in bindings:
            ref = stage_input.artifacts.get(role)
            if ref is None or ref.sha256 is None:
                _fail(
                    "MD.GROMACS_STAGE_ARTIFACT_MISSING",
                    f"stage input is missing hashed artifact role {role!r}",
                )
            registered_ref = source_refs.get(path)
            if require_system_artifact and registered_ref is None:
                _fail(
                    "MD.GROMACS_INPUT_UNREGISTERED",
                    f"topology input {path!r} is absent from system-build artifacts",
                )
            if registered_ref is not None and registered_ref.sha256 != ref.sha256:
                _fail(
                    "MD.GROMACS_STAGE_ARTIFACT_HASH_MISMATCH",
                    f"stage input role {role!r} differs from registered artifact {path!r}",
                )
        return result, parameters, stage

    @staticmethod
    def _validate_segment(stage: MDStage, parameters: GromacsStagePlanParameters) -> None:
        if stage.length_ns is None or stage.length_ns <= 0:
            _fail(
                "MD.GROMACS_SEGMENT_DURATION_UNKNOWN",
                "production segment duration must be known from n_steps × timestep_fs",
            )
        if parameters.target_ns is not None:
            segment_count = parameters.target_ns / stage.length_ns
            if not math.isclose(segment_count, round(segment_count), rel_tol=1e-9, abs_tol=1e-9):
                _fail(
                    "MD.GROMACS_TARGET_NOT_SEGMENT_MULTIPLE",
                    f"target {parameters.target_ns:g} ns is not an integer multiple of the "
                    f"configured {stage.length_ns:g} ns production segment",
                )
            if parameters.segment_index > round(segment_count):
                _fail(
                    "MD.GROMACS_SEGMENT_INDEX_INVALID",
                    f"segment {parameters.segment_index} exceeds target of "
                    f"{round(segment_count)} segments",
                )
        if parameters.segment_index == 1 and parameters.previous_checkpoint_path is not None:
            _fail(
                "MD.GROMACS_SEGMENT_INVALID",
                "the first production segment cannot consume a previous-segment checkpoint",
            )
        if parameters.segment_index > 1 and parameters.resume_checkpoint_path is None:
            if parameters.previous_checkpoint_path is None:
                _fail(
                    "MD.GROMACS_CHECKPOINT_MISSING",
                    "a continued production segment requires its previous segment checkpoint",
                )
            if parameters.coordinates_path is None or not parameters.coordinates_path.endswith(
                ".gro"
            ):
                _fail(
                    "MD.GROMACS_COORDINATES_INVALID",
                    "a continued production segment must start from the previous segment GRO file",
                )


def _fail(code: str, message: str) -> NoReturn:
    raise GromacsPlanError(code, message)
