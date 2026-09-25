"""GROMACS SASA adapter using the engine-neutral trajectory-analysis port."""

from __future__ import annotations

import math
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import Field, JsonValue, PositiveFloat, field_validator

from caddsuite.contracts.analysis import (
    MetricDefinition,
    MetricSeries,
    TrajectoryAnalysisRequest,
    TrajectoryAnalysisResult,
    TrajectoryMetric,
    TrajectoryProcessingResult,
    TrajectoryTransform,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, NonEmptyStr, SoftwareRef
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.ports.adapters import CommandStep, ExecutionPlan
from caddsuite.ports.trajectory_analysis import TrajectoryAnalysisCapabilities
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class GromacsSasaPlanError(ValueError):
    """The request, selection, or GROMACS worker plan is incompatible."""


class GromacsSasaParameters(ContractModel):
    gmx_executable: NonEmptyStr
    python_executable: NonEmptyStr
    worker_script: NonEmptyStr
    request_path: NonEmptyStr = "gromacs-sasa.request.json"
    output_dir: NonEmptyStr = "gromacs-sasa-output"
    probe_radius_A: PositiveFloat = 1.4
    sphere_points: int = Field(default=24, ge=1, le=1_000_000)
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


class GromacsSasaAdapter:
    """Expose GROMACS' native SASA calculation without leaking GROMACS into the core."""

    adapter_id = "caddsuite.gromacs.sasa"
    version = "0.1.0"
    capabilities = TrajectoryAnalysisCapabilities(
        topology_formats=("GROMACS TPR", "TPR"),
        trajectory_formats=("XTC",),
        metrics=(TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA,),
    )

    def _issues(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[str] = []
        if request.topology_format.upper() not in {"TPR", "GROMACS TPR"}:
            issues.append("GROMACS SASA requires a GROMACS TPR topology")
        if request.trajectory_format.upper() != "XTC":
            issues.append("GROMACS SASA adapter currently requires an XTC trajectory")
        if set(request.metrics) != {TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA}:
            issues.append("GROMACS SASA adapter supports only the SASA metric")
        if request.preprocessing_result_id != preprocessing.id:
            issues.append("preprocessing result ID differs from the analysis request")
        if request.simulation_id != preprocessing.simulation_id:
            issues.append("trajectory and preprocessing belong to different simulations")
        if request.trajectory != preprocessing.output_artifacts.get("processed"):
            issues.append("analysis trajectory is not the processed parent output")
        if not any(
            artifact.artifact_id == request.topology.artifact_id
            and artifact.sha256 == request.topology.sha256
            for artifact in preprocessing.source_artifacts.values()
        ):
            issues.append("GROMACS TPR is not a hash-linked source of the processing result")
        if preprocessing.processor.name.casefold() != "gromacs":
            issues.append("GROMACS SASA requires a GROMACS-produced trajectory")
        if request.expected_atom_count != preprocessing.n_atoms:
            issues.append("request atom count differs from the processed trajectory")
        if request.expected_frame_count != preprocessing.n_frames:
            issues.append("request frame count differs from the processed trajectory")
        if not math.isclose(
            request.frame_interval_ps,
            preprocessing.frame_interval_ps,
            rel_tol=0.0,
            abs_tol=1e-5,
        ):
            issues.append("request frame interval differs from the processed trajectory")
        if "surface" not in request.selections or "sasa_output" not in request.selections:
            issues.append("SASA requires verified 'surface' and 'sasa_output' selections")
        elif request.selections["sasa_output"].n_atoms > request.selections["surface"].n_atoms:
            issues.append("SASA output selection cannot contain more atoms than the surface")
        if any(selection.indices is not None for selection in request.selections.values()):
            issues.append("GROMACS SASA currently accepts static named selection expressions")
        if issues:
            return (
                ValidationIssue(
                    code="MD.GROMACS_SASA_INPUT",
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="trajectory", id=str(request.id)),
                    message="; ".join(issues),
                    remediation=(
                        "Use the linked XTC from the GROMACS processor, its source TPR, and "
                        "verified static surface/output selections supported by GROMACS.",
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
        parameters: GromacsSasaParameters,
        staged_paths: dict[str, str],
    ) -> dict[str, object]:
        issues = self._issues(request, preprocessing)
        if issues:
            raise GromacsSasaPlanError(issues[0].message)
        try:
            trajectory_path = staged_paths[str(request.trajectory.artifact_id)]
            topology_path = staged_paths[str(request.topology.artifact_id)]
        except KeyError as exc:
            raise GromacsSasaPlanError(f"missing staged path for artifact {exc.args[0]}") from exc
        aligned = TrajectoryTransform.ALIGN_ROT_TRANS in preprocessing.transforms
        return {
            "protocol": "caddsuite.gromacs-sasa/1",
            "request_id": str(request.id),
            "simulation_id": str(request.simulation_id),
            "trajectory_id": str(request.trajectory_id),
            "preprocessing_result_id": str(preprocessing.id),
            "trajectory": {"path": trajectory_path, "sha256": request.trajectory.sha256},
            "topology": {"path": topology_path, "sha256": request.topology.sha256},
            "gmx_executable": parameters.gmx_executable,
            "timeout_seconds": parameters.timeout_seconds,
            "expected_atom_count": request.expected_atom_count,
            "expected_frame_count": request.expected_frame_count,
            "frame_interval_ps": request.frame_interval_ps,
            "trajectory_first_time_ns": preprocessing.time_range_ps[0] / 1000.0,
            "start_time_ns": request.start_time_ns,
            "end_time_ns": request.end_time_ns,
            "stride": request.stride,
            "metric": TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA.value,
            "probe_radius_A": parameters.probe_radius_A,
            "sphere_points": parameters.sphere_points,
            "use_pbc": not aligned,
            "selections": {
                key: {
                    "description": selection.description,
                    "expected_atom_count": selection.n_atoms,
                }
                for key, selection in request.selections.items()
            },
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
        config = GromacsSasaParameters.model_validate(parameters)
        root = working_directory.resolve(strict=True)
        staged_paths: dict[str, str] = {}
        for artifact in (request.trajectory, request.topology):
            staged = staged_inputs.get(str(artifact.artifact_id))
            if staged is None:
                raise GromacsSasaPlanError(
                    f"missing staged path for artifact {artifact.artifact_id}"
                )
            candidate = staged if staged.is_absolute() else root / staged
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise GromacsSasaPlanError("staged inputs must be files inside the private stage")
            staged_paths[str(artifact.artifact_id)] = resolved.relative_to(root).as_posix()
        self.worker_request(request, preprocessing, config, staged_paths)
        output = root.joinpath(*PurePosixPath(config.output_dir).parts)
        if (
            output.exists()
            or output.is_symlink()
            or not output.resolve(strict=False).is_relative_to(root)
        ):
            raise GromacsSasaPlanError(
                "GROMACS SASA output path exists or escapes the private stage"
            )
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
        selection_outputs = tuple(
            f"{prefix}/{name}.{extension}"
            for name in ("surface", "sasa_output")
            for extension in ("ndx", "count.xvg")
        )
        return ExecutionPlan(
            commands=(command,),
            expected_outputs=(
                f"{prefix}/result.json",
                f"{prefix}/commands.json",
                f"{prefix}/sasa.csv",
                f"{prefix}/sasa.xvg",
                *selection_outputs,
                *(
                    f"{prefix}/{name}.{suffix}.txt"
                    for name in (
                        "gromacs_version",
                        "validate_surface_selection",
                        "validate_sasa_output_selection",
                        "gromacs_sasa",
                    )
                    for suffix in ("stdout", "stderr")
                ),
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
            raise GromacsSasaPlanError("request lineage or adapter compatibility failed")
        metric_data = worker_result.get("metric")
        metadata = worker_result.get("metadata")
        selection_receipts = worker_result.get("selection_receipts")
        if (
            worker_result.get("protocol") != "caddsuite.gromacs-sasa/1"
            or worker_result.get("request_id") != str(request.id)
            or worker_result.get("simulation_id") != str(request.simulation_id)
            or worker_result.get("trajectory_id") != str(request.trajectory_id)
            or worker_result.get("preprocessing_result_id") != str(preprocessing.id)
            or not isinstance(metric_data, dict)
            or not isinstance(metadata, dict)
            or not isinstance(selection_receipts, dict)
        ):
            raise GromacsSasaPlanError("GROMACS SASA worker result or lineage is malformed")
        required_engine_roles = {
            "sasa_xvg",
            "surface_selection_index",
            "surface_selection_count",
            "sasa_output_selection_index",
            "sasa_output_selection_count",
        }
        if (
            metadata.get("trajectory_sha256") != request.trajectory.sha256
            or metadata.get("topology_sha256") != request.topology.sha256
            or metadata.get("n_atoms") != request.expected_atom_count
            or metadata.get("expected_frame_count") != request.expected_frame_count
        ):
            raise GromacsSasaPlanError("worker source hashes or dimensions differ from request")
        if metric_data.get("metric") != TrajectoryMetric.SOLVENT_ACCESSIBLE_SURFACE_AREA.value:
            raise GromacsSasaPlanError("worker returned a different metric")
        output_name = metric_data.get("name")
        output_hash = metric_data.get("sha256")
        engine_name = metric_data.get("engine_file")
        engine_hash = metric_data.get("engine_sha256")
        if (
            output_name != "sasa"
            or metric_data.get("unit") != "Å²"
            or metric_data.get("file") != "sasa.csv"
            or metric_artifacts.keys() != {"sasa"}
            or (engine_artifacts or {}).keys() != required_engine_roles
        ):
            raise GromacsSasaPlanError("metric artifact roles do not match the worker output")
        metric_artifact = metric_artifacts["sasa"]
        engine_artifact = (engine_artifacts or {})["sasa_xvg"]
        if (
            metric_artifact.sha256 is None
            or metric_artifact.sha256 != output_hash
            or engine_artifact.sha256 is None
            or engine_artifact.sha256 != engine_hash
            or engine_name != "sasa.xvg"
            or raw_result_artifact.sha256 is None
        ):
            raise GromacsSasaPlanError("metric, raw engine, or normalized output hashes differ")
        for selection_key in ("surface", "sasa_output"):
            receipt = selection_receipts.get(selection_key)
            if not isinstance(receipt, dict):
                raise GromacsSasaPlanError("worker selection receipts are incomplete")
            index_role = f"{selection_key}_selection_index"
            count_role = f"{selection_key}_selection_count"
            index_artifact = (engine_artifacts or {})[index_role]
            count_artifact = (engine_artifacts or {})[count_role]
            if (
                receipt.get("description") != request.selections[selection_key].description
                or receipt.get("n_atoms") != request.selections[selection_key].n_atoms
                or receipt.get("index_file") != f"{selection_key}.ndx"
                or receipt.get("count_file") != f"{selection_key}.count.xvg"
                or receipt.get("index_sha256") != index_artifact.sha256
                or receipt.get("count_sha256") != count_artifact.sha256
            ):
                raise GromacsSasaPlanError(
                    f"selection receipt artifacts differ for {selection_key!r}"
                )
        summary_raw = metric_data.get("summary")
        if not isinstance(summary_raw, dict):
            raise GromacsSasaPlanError("SASA summary is malformed")
        summary: dict[str, float] = {}
        for key, value in summary_raw.items():
            if (
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise GromacsSasaPlanError("SASA summary has a non-finite or non-numeric value")
            summary[key] = float(value)
        version = metadata.get("gromacs_version")
        if not isinstance(version, str) or not version:
            raise GromacsSasaPlanError("worker did not report a GROMACS version")
        warnings = metadata.get("warnings", [])
        if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
            raise GromacsSasaPlanError("worker warning list is malformed")
        warning_note = " GROMACS reported: " + " | ".join(warnings) if warnings else ""
        metric = MetricSeries(
            name="sasa",
            definition=MetricDefinition(
                target_selection=request.selections["sasa_output"].description,
                notes=(
                    "GROMACS Double Cube SASA; surface selection: "
                    f"{request.selections['surface'].description}; probe "
                    f"{metadata.get('probe_radius_A')} Å; "
                    f"{metadata.get('sphere_points')} points; "
                    f"periodic boundaries={'on' if metadata.get('use_pbc') else 'off'}."
                    + warning_note
                ),
            ),
            unit="Å²",
            axis="time_ns",
            value_column="value",
            series=metric_artifact,
            summary=summary,
            window_ns=(request.start_time_ns, request.end_time_ns),
        )
        expected_inputs = {request.trajectory.artifact_id, request.topology.artifact_id}
        if not expected_inputs.issubset({item.artifact_id for item in source_artifacts.values()}):
            raise GromacsSasaPlanError("normalized result omitted a request input artifact")
        if any(
            artifact.sha256 is None
            for artifact in (*source_artifacts.values(), *log_artifacts.values())
        ):
            raise GromacsSasaPlanError("all source and log artifacts must be hash-linked")
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
            parameters=cast(
                dict[str, JsonValue],
                {
                    "method": "GROMACS gmx sasa",
                    "probe_radius_A": metadata.get("probe_radius_A"),
                    "sphere_points": metadata.get("sphere_points"),
                    "use_pbc": metadata.get("use_pbc"),
                    "surface_selection": request.selections["surface"].description,
                    "output_selection": request.selections["sasa_output"].description,
                    "frame_interval_ps": request.frame_interval_ps,
                    "start_time_ns": request.start_time_ns,
                    "end_time_ns": request.end_time_ns,
                    "stride": request.stride,
                    "warnings": warnings,
                },
            ),
            source_artifacts=source_artifacts,
            raw_result=raw_result_artifact,
            engine_artifacts=engine_artifacts or {},
            log_artifacts=log_artifacts,
            metrics=(metric,),
        )
