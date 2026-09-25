"""GROMACS trajectory processing adapter.

This adapter translates normalized transform requests into a private, stdlib-only worker
invocation. GROMACS flags, index-group selection, and worker protocol stay in this adapter; the
workflow engine sees only the shared trajectory-processing port.
"""

from __future__ import annotations

import math
import re
from pathlib import Path, PurePosixPath
from typing import Annotated, cast

from pydantic import Field, JsonValue, field_validator, model_validator

from caddsuite.contracts.analysis import (
    TrajectoryProcessingRequest,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.trajectory_processing import TrajectoryProcessingCapabilities
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class GromacsTrajectoryPlanError(ValueError):
    """A trajectory request cannot be safely planned for the GROMACS worker."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GromacsTrajectoryPlanError(
            "MD.GROMACS_TRAJECTORY_RESULT_METADATA", f"worker {field} is not numeric"
        )
    number = float(value)
    if not math.isfinite(number):
        raise GromacsTrajectoryPlanError(
            "MD.GROMACS_TRAJECTORY_RESULT_METADATA", f"worker {field} is not finite"
        )
    return number


def _canonical_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"path must be a canonical relative path: {value!r}")
    return value


class GromacsTrajectoryProcessorParameters(ContractModel):
    """Paths and engine-local selection settings for one isolated processing job."""

    gmx_executable: NonEmptyStr
    python_executable: NonEmptyStr
    request_path: NonEmptyStr = "trajectory-processing.request.json"
    output_dir: NonEmptyStr = "trajectory-processing-output"
    output_prefix: NonEmptyStr = "trajectory"
    input_paths: dict[str, NonEmptyStr] = Field(min_length=1)
    index_artifact: ArtifactRef | None = None
    output_group_index: Annotated[int, Field(ge=0)] = 0
    output_group_name: NonEmptyStr = "System"
    output_group_atom_count: Annotated[int, Field(ge=1)]
    fit_group_index: Annotated[int, Field(ge=0)] | None = None
    fit_group_name: NonEmptyStr | None = None
    fit_group_atom_count: Annotated[int, Field(ge=1)] | None = None
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400)] = 3600

    @field_validator("request_path", "output_dir")
    @classmethod
    def _safe_relative_paths(cls, value: str) -> str:
        return _canonical_relative_path(value)

    @field_validator("input_paths")
    @classmethod
    def _safe_input_paths(cls, values: dict[str, str]) -> dict[str, str]:
        return {artifact_id: _canonical_relative_path(path) for artifact_id, path in values.items()}

    @field_validator("output_prefix")
    @classmethod
    def _safe_prefix(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value) or value in {".", ".."}:
            raise ValueError("output_prefix must be a safe filename stem")
        return value

    @field_validator("gmx_executable", "python_executable")
    @classmethod
    def _safe_executable(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("executable cannot contain a NUL byte")
        return value

    @model_validator(mode="after")
    def _index_is_hash_linked(self) -> GromacsTrajectoryProcessorParameters:
        if self.index_artifact is not None and self.index_artifact.sha256 is None:
            raise ValueError("GROMACS index artifact must include a SHA-256 hash")
        fit_values = (self.fit_group_index, self.fit_group_name, self.fit_group_atom_count)
        if any(value is None for value in fit_values) and any(
            value is not None for value in fit_values
        ):
            raise ValueError("fit group index, name, and atom count must be configured together")
        return self


class GromacsTrajectoryProcessor:
    """GROMACS implementation of the engine-neutral trajectory-processing port."""

    adapter_id = "caddsuite.trajectory.gromacs"
    version = "0.1.0"
    capabilities = TrajectoryProcessingCapabilities(
        input_formats=("XTC",),
        topology_formats=("GROMACS TPR",),
        output_formats=("XTC",),
        transforms=tuple(TrajectoryTransform),
        supports_multiple_segments=True,
        requires_connectivity_for_pbc=True,
    )

    def validate_request(
        self,
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
    ) -> tuple[ValidationIssue, ...]:
        try:
            self._resolve(request, parameters)
        except (GromacsTrajectoryPlanError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, GromacsTrajectoryPlanError)
                else "MD.GROMACS_TRAJECTORY_CONFIG_INVALID"
            )
            return (
                ValidationIssue(
                    code=code,
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="trajectory", id=str(request.id)),
                    message=str(exc),
                    remediation=(
                        "Resolve the reported trajectory/topology/selection mismatch "
                        "before processing.",
                    ),
                    rule_version="1",
                ),
            )
        return ()

    def worker_request(
        self,
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        """Build the JSON payload which the application stages at ``request_path``."""
        config = self._resolve(request, parameters)
        paths = config.input_paths
        topology = request.topology
        segments = []
        for segment in request.segments:
            artifact_id = str(segment.artifact.artifact_id)
            segments.append(
                {
                    "path": paths[artifact_id],
                    "sha256": segment.artifact.sha256,
                    "output_start_time_ps": segment.output_start_time_ps,
                    "n_frames": segment.n_frames,
                    "frame_interval_ps": segment.frame_interval_ps,
                }
            )
        index_path = None
        index_sha256 = None
        if config.index_artifact is not None:
            index_id = str(config.index_artifact.artifact_id)
            index_path = paths[index_id]
            index_sha256 = config.index_artifact.sha256
        return {
            "protocol": "caddsuite.gromacs-trajectory-worker/1",
            "topology_path": paths[str(topology.artifact_id)],
            "topology_sha256": topology.sha256,
            "topology_format": request.topology_format,
            "topology_has_connectivity": request.topology_has_connectivity,
            "expected_atom_count": request.expected_atom_count,
            "trajectory_format": request.trajectory_format,
            "segments": segments,
            "transforms": [transform.value for transform in request.transforms],
            "index_path": index_path,
            "index_sha256": index_sha256,
            "output_group_index": config.output_group_index,
            "output_group_name": config.output_group_name,
            "output_group_atom_count": config.output_group_atom_count,
            "fit_group_index": config.fit_group_index,
            "fit_group_name": config.fit_group_name,
            "fit_group_atom_count": config.fit_group_atom_count,
            "gmx_executable": config.gmx_executable,
            "output_dir": config.output_dir,
            "output_prefix": config.output_prefix,
            "timeout_seconds": config.timeout_seconds,
            "request_id": str(request.id),
            "simulation_id": str(request.simulation_id),
        }

    def plan_request(
        self,
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
        *,
        working_directory: Path,
    ) -> ExecutionPlan:
        config = self._resolve(request, parameters)
        command = CommandStep(
            argv=(
                config.python_executable,
                "-m",
                "caddsuite_worker.gromacs_trajectory_worker",
                "--request",
                config.request_path,
            ),
            working_directory=working_directory,
            environment={"PYTHONNOUSERSITE": "1"},
        )
        prefix = config.output_prefix
        out = config.output_dir
        transform_outputs = tuple(
            f"{out}/{prefix}.{index:02d}.{transform.value}.xtc"
            for index, transform in enumerate(request.transforms, start=1)
        )
        expected = (
            f"{out}/{prefix}.raw.xtc",
            *transform_outputs,
            f"{out}/{prefix}.processed.xtc",
            f"{out}/{prefix}.reference.gro",
            f"{out}/{prefix}.atom_masses.json",
            f"{out}/result.json",
            f"{out}/commands.json",
        )
        return ExecutionPlan(commands=(command,), expected_outputs=expected)

    def normalize_result(
        self,
        request: TrajectoryProcessingRequest,
        worker_result: dict[str, object],
        *,
        output_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
        additional_source_artifacts: dict[str, ArtifactRef] | None = None,
    ) -> TrajectoryProcessingResult:
        """Validate the worker receipt against staged artifacts and return a platform contract."""
        if worker_result.get("protocol") != "caddsuite.gromacs-trajectory-worker/1":
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_PROTOCOL",
                "worker result uses an unsupported protocol",
            )
        if worker_result.get("status") != "completed":
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_FAILED",
                "worker result does not report successful completion",
            )
        if worker_result.get("request_id") != str(request.id) or worker_result.get(
            "simulation_id"
        ) != str(request.simulation_id):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_LINEAGE",
                "worker result belongs to a different request or simulation",
            )

        processor = worker_result.get("processor")
        metadata = worker_result.get("metadata")
        raw_parameters = worker_result.get("parameters")
        raw_outputs = worker_result.get("outputs")
        if not isinstance(processor, dict) or not isinstance(metadata, dict):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_INVALID",
                "worker result lacks software or frame metadata",
            )
        if not isinstance(raw_parameters, dict) or not isinstance(raw_outputs, list):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_INVALID",
                "worker result lacks parameters or output records",
            )
        expected_transforms = [transform.value for transform in request.transforms]
        if raw_parameters.get("operations") != expected_transforms:
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_TRANSFORMS",
                "worker transform order differs from the request",
            )
        if (
            raw_parameters.get("output_group_name")
            != (request.output_selection.description if request.output_selection else "System")
            or raw_parameters.get("output_group_atom_count") != request.expected_atom_count
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_SELECTION",
                "worker output selection differs from the verified full-system selection",
            )
        if TrajectoryTransform.ALIGN_ROT_TRANS in request.transforms:
            fit = request.fit_selection
            if (
                fit is None
                or raw_parameters.get("fit_group_name") != fit.description
                or raw_parameters.get("fit_group_atom_count") != fit.n_atoms
            ):
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_RESULT_SELECTION",
                    "worker fit selection differs from the verified fit selection",
                )
        elif any(
            raw_parameters.get(field) is not None
            for field in ("fit_group_index", "fit_group_name", "fit_group_atom_count")
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_SELECTION",
                "worker reported a fit group although alignment was not requested",
            )
        if worker_result.get("topology_sha256") != request.topology.sha256:
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_INPUT_HASH",
                "worker result topology hash differs from the request",
            )
        reported_segments = raw_parameters.get("segments")
        if not isinstance(reported_segments, list) or len(reported_segments) != len(
            request.segments
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_SEGMENTS",
                "worker result segment list differs from the request",
            )
        for requested, reported in zip(request.segments, reported_segments, strict=True):
            if (
                not isinstance(reported, dict)
                or reported.get("sha256") != requested.artifact.sha256
                or reported.get("output_start_time_ps") != requested.output_start_time_ps
                or reported.get("n_frames_declared") != requested.n_frames
                or reported.get("frame_interval_ps_declared") != requested.frame_interval_ps
            ):
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_RESULT_SEGMENTS",
                    "worker segment provenance differs from the requested artifact "
                    "or timing metadata",
                )

        expected_roles: set[str] = {
            "concatenated_raw",
            "processed",
            "reference_structure",
            "atom_masses",
        }
        expected_roles.update(transform.value for transform in request.transforms)
        reported_outputs: dict[str, str] = {}
        for item in raw_outputs:
            if not isinstance(item, dict):
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_RESULT_OUTPUTS", "worker output record is malformed"
                )
            role, digest = item.get("role"), item.get("sha256")
            if not isinstance(role, str) or not isinstance(digest, str) or role in reported_outputs:
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_RESULT_OUTPUTS",
                    "worker output roles or hashes are invalid",
                )
            reported_outputs[role] = digest
        if set(reported_outputs) != expected_roles or set(output_artifacts) != expected_roles:
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_OUTPUTS",
                "registered output roles do not match the worker receipt",
            )
        for role, digest in reported_outputs.items():
            if output_artifacts[role].sha256 != digest:
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_RESULT_OUTPUT_HASH",
                    f"registered artifact hash does not match worker output {role!r}",
                )
        commands_log = log_artifacts.get("commands")
        if commands_log is None or commands_log.sha256 is None:
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_LOGS",
                "a hash-linked commands.json log artifact is required",
            )

        engine_name = processor.get("name")
        engine_version = processor.get("version")
        atom_count = metadata.get("n_atoms")
        frame_count = metadata.get("n_frames")
        interval = metadata.get("frame_interval_ps")
        first_time = metadata.get("first_time_ps")
        last_time = metadata.get("last_time_ps")
        if engine_name != "GROMACS" or not isinstance(engine_version, str):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_METADATA",
                "worker software or frame metadata is invalid",
            )
        if (
            isinstance(atom_count, bool)
            or not isinstance(atom_count, int)
            or isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_METADATA",
                "worker atom/frame counts are invalid",
            )
        interval_value = _required_finite_number(interval, field="frame interval")
        first_time_value = _required_finite_number(first_time, field="first frame time")
        last_time_value = _required_finite_number(last_time, field="last frame time")
        if (
            atom_count != request.expected_atom_count
            or frame_count < 1
            or interval_value <= 0
            or last_time_value < first_time_value
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_RESULT_METADATA",
                "worker frame metadata violates requested system constraints",
            )

        sources = {
            "topology": request.topology,
            **{
                f"segment_{index:03d}": segment.artifact
                for index, segment in enumerate(request.segments, start=1)
            },
            **(additional_source_artifacts or {}),
        }
        return TrajectoryProcessingResult(
            id=new_ulid(),
            request_id=request.id,
            simulation_id=request.simulation_id,
            processor=SoftwareRef(
                name="GROMACS",
                version=engine_version,
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.UNKNOWN,
            ),
            adapter_id=self.adapter_id,
            adapter_version=self.version,
            parameters=cast(dict[str, JsonValue], raw_parameters),
            transforms=request.transforms,
            fit_selection=request.fit_selection,
            output_selection=request.output_selection,
            reference_structure=output_artifacts["reference_structure"],
            atom_masses=output_artifacts["atom_masses"],
            source_artifacts=sources,
            output_artifacts=output_artifacts,
            log_artifacts=log_artifacts,
            n_atoms=atom_count,
            n_frames=frame_count,
            frame_interval_ps=interval_value,
            time_range_ps=(first_time_value, last_time_value),
        )

    @staticmethod
    def _resolve(
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
    ) -> GromacsTrajectoryProcessorParameters:
        config = GromacsTrajectoryProcessorParameters.model_validate(parameters)
        if request.topology_format.casefold() not in {"gromacs tpr", "tpr", "gromacs_tpr"}:
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_TOPOLOGY_FORMAT",
                "GROMACS trajectory processing requires a GROMACS TPR, "
                f"got {request.topology_format!r}",
            )
        if request.trajectory_format.casefold() != "xtc":
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_FORMAT",
                f"this adapter accepts XTC trajectory segments, got {request.trajectory_format!r}",
            )
        unsupported = set(request.transforms).difference(
            GromacsTrajectoryProcessor.capabilities.transforms
        )
        if unsupported:
            names = ", ".join(sorted(transform.value for transform in unsupported))
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_TRANSFORM_UNSUPPORTED",
                f"GROMACS trajectory adapter does not support transforms: {names}",
            )
        if (
            config.output_group_atom_count != request.expected_atom_count
            or config.output_group_name.casefold() != "system"
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_OUTPUT_SELECTION",
                "PBC transforms must process the complete MD system; select the validated "
                "System group with its exact atom count",
            )
        alignment = TrajectoryTransform.ALIGN_ROT_TRANS in request.transforms
        if alignment:
            fit_selection = request.fit_selection
            output_selection = request.output_selection
            if fit_selection is None or output_selection is None:
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_FIT_SELECTION",
                    "alignment requires verified fit and output selection contracts",
                )
            if (
                not fit_selection.verified
                or not output_selection.verified
                or fit_selection.description.casefold() != str(config.fit_group_name).casefold()
                or fit_selection.n_atoms != config.fit_group_atom_count
                or output_selection.description.casefold() != config.output_group_name.casefold()
                or output_selection.n_atoms != config.output_group_atom_count
            ):
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_FIT_SELECTION",
                    "fit/output group names and atom counts must match the verified selections",
                )
            selection_indices = (fit_selection.indices, output_selection.indices)
            if any(index is not None for index in selection_indices):
                if (
                    any(index is None for index in selection_indices)
                    or fit_selection.indices != output_selection.indices
                    or config.index_artifact != fit_selection.indices
                ):
                    raise GromacsTrajectoryPlanError(
                        "MD.GROMACS_TRAJECTORY_INDEX_MISMATCH",
                        "fit and output selections must share the same hash-linked "
                        "GROMACS index artifact",
                    )
            elif config.index_artifact is not None:
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_INDEX_MISMATCH",
                    "an index artifact must be linked by both verified selection contracts",
                )
            elif (
                config.fit_group_index != 1
                or config.fit_group_name != "Protein"
                or config.output_group_index != 0
            ):
                raise GromacsTrajectoryPlanError(
                    "MD.GROMACS_TRAJECTORY_GROUP_UNVERIFIED",
                    "without a custom index artifact, only the validated GROMACS default "
                    "Protein/System groups are accepted",
                )
        elif any(
            value is not None
            for value in (
                config.fit_group_index,
                config.fit_group_name,
                config.fit_group_atom_count,
            )
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_FIT_SELECTION",
                "fit group configuration is present but the request does not include alignment",
            )
        required_ids = {
            str(request.topology.artifact_id),
            *(str(segment.artifact.artifact_id) for segment in request.segments),
        }
        if config.index_artifact is not None:
            required_ids.add(str(config.index_artifact.artifact_id))
        if set(config.input_paths) != required_ids:
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_INPUT_PATHS",
                "staged input paths must map exactly to the hashed topology, trajectory "
                "segments, and optional index artifact",
            )
        if config.index_artifact is None and (
            config.output_group_index != 0
            or config.output_group_name != "System"
            or (alignment and (config.fit_group_index != 1 or config.fit_group_name != "Protein"))
        ):
            raise GromacsTrajectoryPlanError(
                "MD.GROMACS_TRAJECTORY_GROUP_UNVERIFIED",
                "a non-default System group index requires a hash-linked index artifact",
            )
        return config
