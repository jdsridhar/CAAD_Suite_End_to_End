"""MDAnalysis validation-only processor for coordinate/trajectory pairs without edits."""

from __future__ import annotations

import math
from pathlib import Path, PurePosixPath
from typing import NoReturn

from pydantic import Field, field_validator, model_validator

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


class MDAnalysisTrajectoryProcessorParameters(ContractModel):
    python_executable: NonEmptyStr
    worker_script: NonEmptyStr
    input_paths: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    request_path: NonEmptyStr = "mdanalysis-trajectory.request.json"
    output_path: NonEmptyStr = "mdanalysis-trajectory.result.json"
    timeout_seconds: int = Field(default=3600, ge=1, le=86_400)

    @field_validator("request_path", "output_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
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

    @model_validator(mode="after")
    def _control_paths_are_distinct(self) -> MDAnalysisTrajectoryProcessorParameters:
        if self.request_path == self.output_path:
            raise ValueError("request_path and output_path must be different")
        return self


class MDAnalysisTrajectoryProcessor:
    """Validate one PDB/DCD pair and preserve the original DCD as processed output.

    This adapter performs no PBC correction, fitting, concatenation, or coordinate editing.
    It is intended for formats such as OpenMM DCD/PDB whose coordinates are already supplied
    as a single-system trajectory. Callers must choose scientifically justified transforms
    in a separate compatible processing stage when needed.
    """

    adapter_id = "caddsuite.trajectory.mdanalysis"
    version = "0.1.0"
    capabilities = TrajectoryProcessingCapabilities(
        input_formats=("DCD",),
        topology_formats=("PDB",),
        output_formats=("DCD",),
        transforms=(TrajectoryTransform.VALIDATE_ONLY,),
        supports_multiple_segments=False,
        requires_connectivity_for_pbc=False,
    )

    def validate_request(
        self,
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
    ) -> tuple[ValidationIssue, ...]:
        problems: list[str] = []
        if request.topology_format.upper() not in self.capabilities.topology_formats:
            problems.append("MDAnalysis validation requires a PDB topology")
        if request.trajectory_format.upper() not in self.capabilities.input_formats:
            problems.append("MDAnalysis validation requires a DCD trajectory")
        if len(request.segments) != 1:
            problems.append("MDAnalysis validation accepts exactly one trajectory artifact")
        elif request.segments[0].n_frames < 2:
            problems.append("MDAnalysis validation requires at least two frames")
        if request.transforms != (TrajectoryTransform.VALIDATE_ONLY,):
            problems.append("MDAnalysis validation supports validate_only and no coordinate edits")
        input_paths = parameters.get("input_paths")
        expected_ids = {str(request.topology.artifact_id)} | {
            str(segment.artifact.artifact_id) for segment in request.segments
        }
        if (
            not isinstance(input_paths, dict)
            or set(input_paths) != expected_ids
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in input_paths.items()
            )
        ):
            problems.append("two staged input paths for topology and trajectory are required")
        elif any(not _is_canonical_relative_path(value) for value in input_paths.values()):
            problems.append("staged input paths must be confined canonical relative paths")
        if problems:
            return (
                ValidationIssue(
                    code="MD.MDA_TRAJECTORY_INPUT",
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="trajectory", id=str(request.id)),
                    message="; ".join(problems),
                    remediation=(
                        "Provide one hash-linked PDB/DCD pair and select validate_only; this "
                        "processor does not modify coordinates or perform PBC transforms.",
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
        issues = self.validate_request(request, parameters)
        if issues:
            raise ValueError(issues[0].message)
        paths = parameters["input_paths"]
        if not isinstance(paths, dict):
            raise ValueError("input_paths must be an artifact-id mapping")
        segment = request.segments[0]
        topology_path = paths[str(request.topology.artifact_id)]
        trajectory_path = paths[str(segment.artifact.artifact_id)]
        if not isinstance(topology_path, str) or not isinstance(trajectory_path, str):
            raise ValueError("staged input paths must be strings")
        for path in (topology_path, trajectory_path):
            _validate_relative_path(path, "staged input path")
        return {
            "protocol": "caddsuite.mdanalysis-trajectory/1",
            "request_id": str(request.id),
            "simulation_id": str(request.simulation_id),
            "topology": {"path": topology_path, "sha256": request.topology.sha256},
            "trajectory": {"path": trajectory_path, "sha256": segment.artifact.sha256},
            "expected_atom_count": request.expected_atom_count,
            "expected_frame_count": segment.n_frames,
            "output_start_time_ps": segment.output_start_time_ps,
            "frame_interval_ps": segment.frame_interval_ps,
        }

    def plan_request(
        self,
        request: TrajectoryProcessingRequest,
        parameters: dict[str, object],
        *,
        working_directory: Path,
    ) -> ExecutionPlan:
        del request
        config = MDAnalysisTrajectoryProcessorParameters.model_validate(parameters)
        root = working_directory.resolve(strict=True)
        output = root.joinpath(*PurePosixPath(config.output_path).parts)
        if not output.resolve(strict=False).is_relative_to(root):
            raise ValueError("MDAnalysis trajectory output path escapes the private stage")
        request_path = root.joinpath(*PurePosixPath(config.request_path).parts)
        if not request_path.resolve(strict=False).is_relative_to(root):
            raise ValueError("MDAnalysis trajectory request path escapes the private stage")
        if output.exists() or output.is_symlink():
            raise ValueError("MDAnalysis trajectory worker refuses an existing output")
        return ExecutionPlan(
            commands=(
                CommandStep(
                    argv=(
                        config.python_executable,
                        config.worker_script,
                        "--request",
                        config.request_path,
                        "--output",
                        config.output_path,
                    ),
                    working_directory=root,
                    environment={"PYTHONNOUSERSITE": "1"},
                ),
            ),
            expected_outputs=(config.output_path,),
        )

    def normalize_result(
        self,
        request: TrajectoryProcessingRequest,
        worker_result: dict[str, object],
        *,
        output_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
        additional_source_artifacts: dict[str, ArtifactRef] | None = None,
    ) -> TrajectoryProcessingResult:
        if worker_result.get("protocol") != "caddsuite.mdanalysis-trajectory/1":
            _fail("MD.MDA_TRAJECTORY_PROTOCOL", "worker result protocol is unsupported")
        if (
            worker_result.get("status") != "validated"
            or worker_result.get("request_id") != str(request.id)
            or worker_result.get("simulation_id") != str(request.simulation_id)
        ):
            _fail("MD.MDA_TRAJECTORY_LINEAGE", "worker result status or lineage is invalid")
        metadata = worker_result.get("metadata")
        if not isinstance(metadata, dict) or len(request.segments) != 1:
            _fail("MD.MDA_TRAJECTORY_METADATA", "worker frame metadata is malformed")
        segment = request.segments[0]
        if (
            metadata.get("topology_sha256") != request.topology.sha256
            or metadata.get("trajectory_sha256") != segment.artifact.sha256
            or metadata.get("n_atoms") != request.expected_atom_count
            or metadata.get("n_frames") != segment.n_frames
        ):
            _fail("MD.MDA_TRAJECTORY_SOURCE_MISMATCH", "worker hashes or dimensions differ")
        first = _finite(metadata.get("first_time_ps"), "first_time_ps")
        last = _finite(metadata.get("last_time_ps"), "last_time_ps")
        interval = _finite(metadata.get("frame_interval_ps"), "frame_interval_ps")
        if (
            not math.isclose(first, segment.output_start_time_ps, abs_tol=1e-4, rel_tol=0.0)
            or not math.isclose(interval, segment.frame_interval_ps, abs_tol=1e-4, rel_tol=0.0)
            or not math.isclose(
                last,
                segment.output_end_time_ps,
                abs_tol=1e-4,
                rel_tol=0.0,
            )
        ):
            _fail("MD.MDA_TRAJECTORY_TIMING_MISMATCH", "observed frame times differ from request")
        receipt = output_artifacts.get("receipt")
        if receipt is None or receipt.sha256 is None:
            _fail("MD.MDA_TRAJECTORY_RECEIPT_MISSING", "worker receipt artifact is missing")
        processor = worker_result.get("processor")
        if (
            not isinstance(processor, dict)
            or processor.get("name") != "MDAnalysis"
            or not isinstance(processor.get("version"), str)
            or not processor["version"]
        ):
            _fail("MD.MDA_TRAJECTORY_PROCESSOR_MISSING", "worker MDAnalysis version is missing")
        box = metadata.get("periodic_box_lengths_A_angles_deg")
        if (
            metadata.get("coordinates_modified") is not False
            or not isinstance(box, list)
            or len(box) != 6
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
                for value in box
            )
        ):
            _fail(
                "MD.MDA_TRAJECTORY_METADATA",
                "worker must report an unchanged trajectory and valid periodic box",
            )
        return TrajectoryProcessingResult(
            id=new_ulid(),
            request_id=request.id,
            simulation_id=request.simulation_id,
            compound_id=request.compound_id,
            form_id=request.form_id,
            processor=SoftwareRef(
                name="MDAnalysis",
                version=processor["version"],
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
            adapter_id=self.adapter_id,
            adapter_version=self.version,
            parameters={
                "operation": "validate_only",
                "coordinates_modified": False,
                "observed_first_time_ps": first,
                "observed_last_time_ps": last,
                "observed_frame_interval_ps": interval,
                "periodic_box_lengths_A_angles_deg": box,
            },
            transforms=request.transforms,
            source_artifacts={
                "topology": request.topology,
                "trajectory_1": segment.artifact,
                **(additional_source_artifacts or {}),
            },
            reference_structure=request.topology,
            output_artifacts={
                "processed": segment.artifact,
                "reference_structure": request.topology,
                "validation_receipt": receipt,
            },
            log_artifacts=log_artifacts,
            n_atoms=request.expected_atom_count,
            n_frames=segment.n_frames,
            output_topology_format="PDB",
            output_trajectory_format="DCD",
            frame_interval_ps=interval,
            time_range_ps=(first, last),
        )


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("MD.MDA_TRAJECTORY_METADATA", f"worker {field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        _fail("MD.MDA_TRAJECTORY_METADATA", f"worker {field} must be finite")
    return number


def _validate_relative_path(value: str, label: str) -> None:
    if not _is_canonical_relative_path(value):
        raise ValueError(f"{label} must be a canonical relative path")


def _is_canonical_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(
        value
        and "\\" not in value
        and not path.is_absolute()
        and path.as_posix() == value
        and not any(part in {"", ".", ".."} for part in path.parts)
    )


def _fail(code: str, message: str) -> NoReturn:
    raise ValueError(f"{code}: {message}")
