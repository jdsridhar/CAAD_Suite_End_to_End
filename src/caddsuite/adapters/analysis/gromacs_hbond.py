"""GROMACS trajectory hydrogen-bond counts behind the common analysis port."""

from __future__ import annotations

import math
from pathlib import Path, PurePosixPath

from pydantic import Field, PositiveFloat, field_validator

from caddsuite.contracts.analysis import (
    MetricDefinition,
    MetricSeries,
    TrajectoryAnalysisRequest,
    TrajectoryAnalysisResult,
    TrajectoryMetric,
    TrajectoryProcessingResult,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.trajectory_analysis import TrajectoryAnalysisCapabilities
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class GromacsHbondPlanError(ValueError):
    """The request, lineage, or GROMACS worker plan is incompatible."""


class GromacsHbondParameters(ContractModel):
    gmx_executable: NonEmptyStr
    python_executable: NonEmptyStr
    worker_script: NonEmptyStr
    request_path: NonEmptyStr = "gromacs-hbond.request.json"
    output_dir: NonEmptyStr = "gromacs-hbond-output"
    hbond_distance_nm: PositiveFloat = Field(default=0.35, le=1.0)
    donor_acceptor_angle_deg: PositiveFloat = Field(default=30.0, le=180.0)
    timeout_seconds: int = Field(default=3600, ge=1, le=86_400)

    @field_validator("request_path", "output_dir")
    @classmethod
    def _safe_relative(cls, value: str) -> str:
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


class GromacsHbondAdapter:
    """Count chemically assigned protein-ligand H-bonds from a GROMACS TPR/XTC pair."""

    adapter_id = "caddsuite.gromacs.hbond"
    version = "0.1.0"
    capabilities = TrajectoryAnalysisCapabilities(
        topology_formats=("GROMACS TPR", "TPR"),
        trajectory_formats=("XTC",),
        metrics=(TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT,),
    )

    def _issues(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
    ) -> tuple[ValidationIssue, ...]:
        problems: list[str] = []
        if request.topology_format.upper() not in {"TPR", "GROMACS TPR"}:
            problems.append("GROMACS hydrogen-bond counts require a GROMACS TPR topology")
        if request.trajectory_format.upper() != "XTC":
            problems.append("GROMACS hydrogen-bond counts currently require XTC")
        if set(request.metrics) != {TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT}:
            problems.append("this adapter supports only protein-ligand hydrogen-bond counts")
        if request.preprocessing_result_id != preprocessing.id:
            problems.append("preprocessing result ID differs from the request")
        if request.simulation_id != preprocessing.simulation_id:
            problems.append("trajectory and preprocessing belong to different simulations")
        if request.trajectory != preprocessing.output_artifacts.get("processed"):
            problems.append("analysis trajectory is not the processed parent output")
        if not any(
            artifact.artifact_id == request.topology.artifact_id
            and artifact.sha256 == request.topology.sha256
            for artifact in preprocessing.source_artifacts.values()
        ):
            problems.append("GROMACS TPR is not a hash-linked source of the processing result")
        if request.index_file is None or not any(
            artifact.artifact_id == request.index_file.artifact_id
            and artifact.sha256 == request.index_file.sha256
            for artifact in preprocessing.source_artifacts.values()
        ):
            problems.append("GROMACS index file is not a hash-linked processing input")
        if preprocessing.processor.name.casefold() != "gromacs":
            problems.append("GROMACS hydrogen-bond counts require a GROMACS-processed trajectory")
        if request.expected_atom_count != preprocessing.n_atoms:
            problems.append("request atom count differs from the processed trajectory")
        if request.expected_frame_count != preprocessing.n_frames:
            problems.append("request frame count differs from the processed trajectory")
        if not math.isclose(
            request.frame_interval_ps,
            preprocessing.frame_interval_ps,
            rel_tol=0.0,
            abs_tol=1e-5,
        ):
            problems.append("request frame interval differs from the processed trajectory")
        if not {"protein", "ligand"}.issubset(request.selections):
            problems.append("hydrogen-bond analysis needs verified protein and ligand selections")
        else:
            if any(
                not request.selections[key].description.strip()
                or "\n" in request.selections[key].description
                or "\r" in request.selections[key].description
                for key in ("protein", "ligand")
            ):
                problems.append("GROMACS hbond group names must be single-line")
            if request.selections["protein"].n_atoms + request.selections["ligand"].n_atoms > (
                request.expected_atom_count
            ):
                problems.append("protein and ligand selections cannot exceed total atom count")
        if problems:
            return (
                ValidationIssue(
                    code="MD.GROMACS_HBOND_INPUT",
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="trajectory", id=str(request.id)),
                    message="; ".join(problems),
                    remediation=(
                        "Use the hash-linked processed XTC and source GROMACS TPR, with distinct "
                        "verified static GROMACS selections for protein and ligand.",
                    ),
                    rule_version="1",
                ),
            )
        return ()

    def validate_request(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
    ) -> tuple[ValidationIssue, ...]:
        return self._issues(request, preprocessing)

    def worker_request(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
        parameters: GromacsHbondParameters,
        staged_paths: dict[str, str],
    ) -> dict[str, object]:
        issues = self._issues(request, preprocessing)
        if issues:
            raise GromacsHbondPlanError(issues[0].message)
        try:
            trajectory_path = staged_paths[str(request.trajectory.artifact_id)]
            topology_path = staged_paths[str(request.topology.artifact_id)]
            if request.index_file is None:
                raise GromacsHbondPlanError("GROMACS H-bond analysis needs an index file")
            index_path = staged_paths[str(request.index_file.artifact_id)]
        except KeyError as exc:
            raise GromacsHbondPlanError(f"missing staged path for artifact {exc.args[0]}") from exc
        return {
            "protocol": "caddsuite.gromacs-hbond/1",
            "request_id": str(request.id),
            "simulation_id": str(request.simulation_id),
            "trajectory_id": str(request.trajectory_id),
            "preprocessing_result_id": str(preprocessing.id),
            "trajectory": {"path": trajectory_path, "sha256": request.trajectory.sha256},
            "topology": {"path": topology_path, "sha256": request.topology.sha256},
            "index_file": {"path": index_path, "sha256": request.index_file.sha256},
            "gmx_executable": parameters.gmx_executable,
            "timeout_seconds": parameters.timeout_seconds,
            "expected_atom_count": request.expected_atom_count,
            "expected_frame_count": request.expected_frame_count,
            "frame_interval_ps": request.frame_interval_ps,
            "trajectory_first_time_ns": preprocessing.time_range_ps[0] / 1000.0,
            "start_time_ns": request.start_time_ns,
            "end_time_ns": request.end_time_ns,
            "stride": request.stride,
            "protein_selection": {
                "group_name": request.selections["protein"].description,
                "expected_atom_count": request.selections["protein"].n_atoms,
            },
            "ligand_selection": {
                "group_name": request.selections["ligand"].description,
                "expected_atom_count": request.selections["ligand"].n_atoms,
            },
            "hbond_distance_nm": parameters.hbond_distance_nm,
            "donor_acceptor_angle_deg": parameters.donor_acceptor_angle_deg,
            "output_dir": parameters.output_dir,
        }

    def plan_request(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
        *,
        parameters: dict[str, object],
        staged_inputs: dict[str, Path],
        working_directory: Path,
    ) -> ExecutionPlan:
        config = GromacsHbondParameters.model_validate(parameters)
        root = working_directory.resolve(strict=True)
        staged_paths: dict[str, str] = {}
        artifacts = (request.trajectory, request.topology, request.index_file)
        for artifact in artifacts:
            if artifact is None:
                raise GromacsHbondPlanError("GROMACS H-bond analysis needs a hash-linked index")
            staged = staged_inputs.get(str(artifact.artifact_id))
            if staged is None:
                raise GromacsHbondPlanError(
                    f"missing staged path for artifact {artifact.artifact_id}"
                )
            candidate = staged if staged.is_absolute() else root / staged
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise GromacsHbondPlanError("staged inputs must be files inside the private stage")
            staged_paths[str(artifact.artifact_id)] = resolved.relative_to(root).as_posix()
        payload = self.worker_request(request, preprocessing, config, staged_paths)
        output = root.joinpath(*PurePosixPath(config.output_dir).parts)
        if (
            output.exists()
            or output.is_symlink()
            or not output.resolve(strict=False).is_relative_to(root)
        ):
            raise GromacsHbondPlanError(
                "GROMACS hbond output path exists or escapes the private stage"
            )
        request_file = root.joinpath(*PurePosixPath(config.request_path).parts)
        if (
            request_file.exists()
            or request_file.is_symlink()
            or not request_file.resolve(strict=False).is_relative_to(root)
        ):
            raise GromacsHbondPlanError(
                "GROMACS hbond request path exists or escapes the private stage"
            )
        # The workflow runner writes this validated payload at request_path before execution.
        if payload["protocol"] != "caddsuite.gromacs-hbond/1":
            raise GromacsHbondPlanError("internal worker protocol mismatch")
        command = CommandStep(
            argv=(
                config.python_executable,
                config.worker_script,
                "--request",
                config.request_path,
                "--output-dir",
                config.output_dir,
            ),
            working_directory=root,
            environment={},
        )
        prefix = config.output_dir
        return ExecutionPlan(
            commands=(command,),
            expected_outputs=(
                f"{prefix}/result.json",
                f"{prefix}/commands.json",
                f"{prefix}/hbond_count.csv",
                f"{prefix}/hbond_count.xvg",
                f"{prefix}/gromacs_version.stdout.txt",
                f"{prefix}/gromacs_version.stderr.txt",
                f"{prefix}/gromacs_hbond_help.stdout.txt",
                f"{prefix}/gromacs_hbond_help.stderr.txt",
                f"{prefix}/gromacs_hbond.stdout.txt",
                f"{prefix}/gromacs_hbond.stderr.txt",
            ),
        )

    def normalize_result(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
        worker_result: dict[str, object],
        *,
        metric_artifacts: dict[str, ArtifactRef],
        raw_result_artifact: ArtifactRef,
        source_artifacts: dict[str, ArtifactRef],
        log_artifacts: dict[str, ArtifactRef],
        engine_artifacts: dict[str, ArtifactRef] | None = None,
    ) -> TrajectoryAnalysisResult:
        if self._issues(request, preprocessing):
            raise GromacsHbondPlanError("request lineage or adapter compatibility failed")
        metric_data = worker_result.get("metric")
        metadata = worker_result.get("metadata")
        if (
            worker_result.get("protocol") != "caddsuite.gromacs-hbond/1"
            or worker_result.get("request_id") != str(request.id)
            or worker_result.get("simulation_id") != str(request.simulation_id)
            or worker_result.get("trajectory_id") != str(request.trajectory_id)
            or worker_result.get("preprocessing_result_id") != str(preprocessing.id)
            or not isinstance(metric_data, dict)
            or not isinstance(metadata, dict)
        ):
            raise GromacsHbondPlanError("GROMACS hbond worker result or lineage is malformed")
        if (
            metric_data.get("metric") != TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT.value
            or metric_data.get("file") != "hbond_count.csv"
            or metric_data.get("engine_file") != "hbond_count.xvg"
            or metric_artifacts.keys() != {"hbond_count"}
            or (engine_artifacts or {}).keys() != {"hbond_xvg"}
        ):
            raise GromacsHbondPlanError("worker metric artifact roles do not match its output")
        metric_artifact = metric_artifacts["hbond_count"]
        xvg_artifact = (engine_artifacts or {})["hbond_xvg"]
        if (
            metric_artifact.sha256 is None
            or metric_artifact.sha256 != metric_data.get("sha256")
            or xvg_artifact.sha256 is None
            or xvg_artifact.sha256 != metric_data.get("engine_sha256")
            or raw_result_artifact.sha256 is None
            or metadata.get("trajectory_sha256") != request.trajectory.sha256
            or metadata.get("topology_sha256") != request.topology.sha256
            or metadata.get("n_atoms") != request.expected_atom_count
            or metadata.get("input_frame_count") != request.expected_frame_count
        ):
            raise GromacsHbondPlanError("worker hashes or dimensions differ from the request")
        if request.index_file is None:
            raise GromacsHbondPlanError("GROMACS H-bond analysis needs a hash-linked index")
        if metadata.get("index_sha256") != request.index_file.sha256:
            raise GromacsHbondPlanError("worker index-file hash differs from the request")
        expected = {
            request.trajectory.artifact_id,
            request.topology.artifact_id,
            request.index_file.artifact_id,
        }
        if not expected.issubset({artifact.artifact_id for artifact in source_artifacts.values()}):
            raise GromacsHbondPlanError("normalized result omitted a request input artifact")
        if any(
            artifact.sha256 is None
            for artifact in (*source_artifacts.values(), *log_artifacts.values())
        ):
            raise GromacsHbondPlanError("all source and log artifacts must be hash-linked")
        summary_raw = metric_data.get("summary")
        if not isinstance(summary_raw, dict):
            raise GromacsHbondPlanError("hydrogen-bond summary is malformed")
        summary: dict[str, float] = {}
        for key, value in summary_raw.items():
            if (
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise GromacsHbondPlanError("hydrogen-bond summary contains invalid values")
            summary[key] = float(value)
        version = metadata.get("gromacs_version")
        if not isinstance(version, str) or not version:
            raise GromacsHbondPlanError("worker did not report the GROMACS version")
        metric = MetricSeries(
            name="protein_ligand_hbond_count",
            definition=MetricDefinition(
                target_selection=request.selections["ligand"].description,
                notes=(
                    "GROMACS topology-assigned geometric hydrogen bonds; protein selection: "
                    f"{request.selections['protein'].description}; donor-acceptor cutoff "
                    f"{metadata.get('hbond_distance_nm')} nm and donor-acceptor-hydrogen angle "
                    f"<= {metadata.get('donor_acceptor_angle_deg')} degrees. Per-frame counts "
                    "do not identify residue pairs or establish interaction persistence."
                ),
            ),
            unit="hydrogen_bonds",
            axis="time_ns",
            value_column="hbond_count",
            series=metric_artifact,
            summary=summary,
            window_ns=(request.start_time_ns, request.end_time_ns),
        )
        return TrajectoryAnalysisResult(
            id=new_ulid(),
            request_id=request.id,
            simulation_id=request.simulation_id,
            trajectory_id=request.trajectory_id,
            preprocessing_result_id=preprocessing.id,
            analyzer=SoftwareRef(
                name="GROMACS",
                version=version,
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.OPEN_SOURCE_COPYLEFT,
            ),
            parameters={
                "adapter_id": self.adapter_id,
                "adapter_version": self.version,
                "metric": TrajectoryMetric.PROTEIN_LIGAND_HBOND_COUNT.value,
                "hbond_distance_nm": metadata["hbond_distance_nm"],
                "donor_acceptor_angle_deg": metadata["donor_acceptor_angle_deg"],
                "donor_elements": metadata["donor_elements"],
                "acceptor_elements": metadata["acceptor_elements"],
                "protein_selection": request.selections["protein"].description,
                "ligand_selection": request.selections["ligand"].description,
                "index_file_sha256": request.index_file.sha256,
                "start_time_ns": request.start_time_ns,
                "end_time_ns": request.end_time_ns,
                "stride": request.stride,
                "periodic_boundary_conditions": "GROMACS default from trajectory box",
            },
            source_artifacts=source_artifacts,
            raw_result=raw_result_artifact,
            engine_artifacts=engine_artifacts or {},
            log_artifacts=log_artifacts,
            metrics=(metric,),
        )
