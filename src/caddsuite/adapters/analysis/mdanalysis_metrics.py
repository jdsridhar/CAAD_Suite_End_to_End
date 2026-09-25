"""MDAnalysis adapter for coordinate-only trajectory metrics."""

from __future__ import annotations

import math
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import Field, JsonValue, field_validator

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


class MDAnalysisPlanError(ValueError):
    """An input, lineage record, or worker receipt cannot be trusted."""


class MDAnalysisMetricsParameters(ContractModel):
    python_executable: NonEmptyStr
    worker_script: NonEmptyStr
    request_path: NonEmptyStr = "trajectory-analysis.request.json"
    output_dir: NonEmptyStr = "trajectory-analysis-output"
    timeout_seconds: int = Field(default=3600, ge=1, le=86_400)

    @staticmethod
    def _safe_relative(value: str) -> str:
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

    @field_validator("request_path", "output_dir")
    @classmethod
    def _validate_output_paths(cls, value: str) -> str:
        return cls._safe_relative(value)


_METRIC_LABELS: dict[TrajectoryMetric, tuple[str, str]] = {
    TrajectoryMetric.BACKBONE_RMSD: ("rmsd_backbone", "Å"),
    TrajectoryMetric.LIGAND_POSE_RMSD: ("rmsd_ligand_pose", "Å"),
    TrajectoryMetric.LIGAND_INTERNAL_RMSD: ("rmsd_ligand_internal", "Å"),
    TrajectoryMetric.PROTEIN_CA_RMSF: ("rmsf_ca", "Å"),
    TrajectoryMetric.PROTEIN_RADIUS_OF_GYRATION: ("rg_protein", "Å"),
    TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE: ("mindist_protein_ligand", "Å"),
    TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT: ("contacts_protein_ligand", "atom_pairs"),
}

_MDA_METRICS = (
    TrajectoryMetric.BACKBONE_RMSD,
    TrajectoryMetric.LIGAND_POSE_RMSD,
    TrajectoryMetric.LIGAND_INTERNAL_RMSD,
    TrajectoryMetric.PROTEIN_CA_RMSF,
    TrajectoryMetric.PROTEIN_RADIUS_OF_GYRATION,
    TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,
    TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT,
)


class MDAnalysisMetricsAdapter:
    """Plan and normalize optional MDAnalysis worker jobs; no MDA import in the core."""

    adapter_id = "caddsuite.mdanalysis.metrics"
    version = "0.1.0"
    capabilities = TrajectoryAnalysisCapabilities(
        topology_formats=("GRO",),
        trajectory_formats=("XTC",),
        metrics=_MDA_METRICS,
    )

    def _issues(
        self,
        request: TrajectoryAnalysisRequest,
        preprocessing: TrajectoryProcessingResult,
    ) -> tuple[ValidationIssue, ...]:
        problems: list[str] = []
        if request.topology_format.upper() not in self.capabilities.topology_formats:
            problems.append("MDAnalysis metrics adapter currently requires a GRO topology")
        if request.trajectory_format.upper() not in self.capabilities.trajectory_formats:
            problems.append("MDAnalysis metrics adapter currently requires an XTC trajectory")
        if set(request.metrics).difference(self.capabilities.metrics):
            problems.append("one or more requested metrics are unsupported by this adapter")
        if request.preprocessing_result_id != preprocessing.id:
            problems.append("preprocessing result ID differs from the request lineage")
        if request.simulation_id != preprocessing.simulation_id:
            problems.append("trajectory and preprocessing belong to different simulations")
        processed = preprocessing.output_artifacts.get("processed")
        if processed != request.trajectory:
            problems.append(
                "analysis trajectory is not the processed artifact from its parent result"
            )
        if (
            request.reference_structure is not None
            and preprocessing.reference_structure != request.reference_structure
        ):
            problems.append("reference structure is not the one registered by preprocessing")
        if request.atom_masses is not None and preprocessing.atom_masses != request.atom_masses:
            problems.append("atom-mass table is not the one registered by preprocessing")
        if (
            preprocessing.n_atoms != request.expected_atom_count
            or preprocessing.n_frames != request.expected_frame_count
            or not math.isclose(
                preprocessing.frame_interval_ps,
                request.frame_interval_ps,
                rel_tol=0.0,
                abs_tol=1e-5,
            )
        ):
            problems.append("trajectory dimensions or frame cadence differ from preprocessing")
        if TrajectoryMetric.LIGAND_POSE_RMSD in request.metrics:
            fit = request.pose_fit_selection
            if (
                TrajectoryTransform.ALIGN_ROT_TRANS not in preprocessing.transforms
                or fit is None
                or preprocessing.fit_selection is None
                or preprocessing.fit_selection.description.casefold() != fit.description.casefold()
                or preprocessing.fit_selection.n_atoms != fit.n_atoms
            ):
                problems.append(
                    "ligand pose RMSD requires coordinates aligned by the same verified "
                    "fit selection"
                )
        elif request.pose_fit_selection is not None:
            problems.append(
                "pose_fit_selection is only meaningful when ligand pose RMSD is requested"
            )
        geometric_metrics = {
            TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,
            TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT,
        }
        if geometric_metrics.intersection(request.metrics) and (
            TrajectoryTransform.ALIGN_ROT_TRANS in preprocessing.transforms
        ):
            transform_order = list(preprocessing.transforms)
            align_index = transform_order.index(TrajectoryTransform.ALIGN_ROT_TRANS)
            required_pbc = (
                TrajectoryTransform.REMOVE_PERIODIC_JUMPS,
                TrajectoryTransform.MAKE_MOLECULES_WHOLE,
            )
            if any(
                transform not in transform_order or transform_order.index(transform) >= align_index
                for transform in required_pbc
            ):
                problems.append(
                    "aligned protein-ligand geometry metrics require periodic jumps removed "
                    "and molecules made whole before fitting"
                )
        if any(selection.indices is not None for selection in request.selections.values()):
            problems.append(
                "this MDAnalysis worker currently accepts named selections, not index files"
            )
        if problems:
            return (
                ValidationIssue(
                    code="MD.MDANALYSIS_METRICS_INPUT",
                    severity=Severity.BLOCKER,
                    subject=SubjectRef(kind="trajectory", id=str(request.id)),
                    message="; ".join(problems),
                    remediation=(
                        "Use a matching GRO/XTC pair, verified named selections, and the linked "
                        "processed trajectory whose recorded fit matches the requested "
                        "pose metric.",
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
        parameters: MDAnalysisMetricsParameters,
        staged_paths: dict[str, str],
    ) -> dict[str, object]:
        issues = self._issues(request, preprocessing)
        if issues:
            raise MDAnalysisPlanError(issues[0].message)
        try:
            trajectory_path = staged_paths[str(request.trajectory.artifact_id)]
            topology_path = staged_paths[str(request.topology.artifact_id)]
            reference_path = (
                staged_paths[str(request.reference_structure.artifact_id)]
                if request.reference_structure is not None
                else None
            )
            mass_path = (
                staged_paths[str(request.atom_masses.artifact_id)]
                if request.atom_masses is not None
                else None
            )
        except KeyError as exc:
            raise MDAnalysisPlanError(f"missing staged path for artifact {exc.args[0]}") from exc
        return {
            "protocol": "caddsuite.mdanalysis-metrics/1",
            "request_id": str(request.id),
            "simulation_id": str(request.simulation_id),
            "trajectory_id": str(request.trajectory_id),
            "preprocessing_result_id": str(preprocessing.id),
            "trajectory": {"path": trajectory_path, "sha256": request.trajectory.sha256},
            "topology": {"path": topology_path, "sha256": request.topology.sha256},
            "reference_structure": (
                {
                    "path": reference_path,
                    "sha256": request.reference_structure.sha256,
                }
                if request.reference_structure is not None
                else None
            ),
            "atom_masses": (
                {"path": mass_path, "sha256": request.atom_masses.sha256}
                if request.atom_masses is not None
                else None
            ),
            "trajectory_format": request.trajectory_format.upper(),
            "topology_format": request.topology_format.upper(),
            "expected_atom_count": request.expected_atom_count,
            "expected_frame_count": request.expected_frame_count,
            "frame_interval_ps": request.frame_interval_ps,
            "reference_frame": request.reference_frame,
            "start_time_ns": request.start_time_ns,
            "end_time_ns": request.end_time_ns,
            "stride": request.stride,
            "contact_cutoff_A": request.contact_cutoff_A,
            "rmsd_weighting": request.rmsd_weighting,
            "distance_mode": (
                "cartesian_unwrapped"
                if TrajectoryTransform.ALIGN_ROT_TRANS in preprocessing.transforms
                else "minimum_image"
            ),
            "metrics": [metric.value for metric in request.metrics],
            "selections": {
                key: {
                    "description": selection.description,
                    "expected_atom_count": selection.n_atoms,
                }
                for key, selection in request.selections.items()
            },
            "pose_fit_selection": (
                {
                    "description": request.pose_fit_selection.description,
                    "expected_atom_count": request.pose_fit_selection.n_atoms,
                }
                if request.pose_fit_selection is not None
                else None
            ),
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
        config = MDAnalysisMetricsParameters.model_validate(parameters)
        root = working_directory.resolve(strict=True)
        staged_paths: dict[str, str] = {}
        required_input_ids = [
            str(request.trajectory.artifact_id),
            str(request.topology.artifact_id),
            *(
                [str(request.reference_structure.artifact_id)]
                if request.reference_structure is not None
                else []
            ),
            *([str(request.atom_masses.artifact_id)] if request.atom_masses is not None else []),
        ]
        for artifact_id in required_input_ids:
            staged = staged_inputs.get(artifact_id)
            if staged is None:
                raise MDAnalysisPlanError(f"missing staged path for artifact {artifact_id}")
            candidate = staged if staged.is_absolute() else root / staged
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise MDAnalysisPlanError("staged input is not a file inside the private stage")
            staged_paths[artifact_id] = resolved.relative_to(root).as_posix()
        self.worker_request(request, preprocessing, config, staged_paths)
        outputs = root.joinpath(*PurePosixPath(config.output_dir).parts)
        if not outputs.resolve(strict=False).is_relative_to(root):
            raise MDAnalysisPlanError("analysis output directory escapes its private stage")
        if outputs.exists() or outputs.is_symlink():
            raise MDAnalysisPlanError("analysis worker refuses an existing output directory")
        command = CommandStep(
            argv=(
                config.python_executable,
                config.worker_script,
                "--request",
                config.request_path,
                "--output-dir",
                config.output_dir,
                "--timeout-seconds",
                str(config.timeout_seconds),
            ),
            working_directory=root,
            environment={},
        )
        metric_outputs = tuple(
            f"{config.output_dir}/{_METRIC_LABELS[metric][0]}.csv" for metric in request.metrics
        )
        return ExecutionPlan(
            commands=(command,),
            expected_outputs=(
                f"{config.output_dir}/result.json",
                f"{config.output_dir}/commands.json",
                *metric_outputs,
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
            raise MDAnalysisPlanError("request lineage or adapter compatibility failed")
        if worker_result.get("protocol") != "caddsuite.mdanalysis-metrics/1":
            raise MDAnalysisPlanError("worker protocol is unknown")
        if (
            worker_result.get("request_id") != str(request.id)
            or worker_result.get("simulation_id") != str(request.simulation_id)
            or worker_result.get("preprocessing_result_id") != str(preprocessing.id)
        ):
            raise MDAnalysisPlanError("worker request or lineage identifiers do not match")
        metadata = worker_result.get("metadata")
        reported_metrics = worker_result.get("metrics")
        if not isinstance(metadata, dict) or not isinstance(reported_metrics, list):
            raise MDAnalysisPlanError("worker result metadata or metrics are malformed")
        if (
            metadata.get("n_atoms") != request.expected_atom_count
            or metadata.get("n_frames") != request.expected_frame_count
            or metadata.get("trajectory_sha256") != request.trajectory.sha256
            or metadata.get("topology_sha256") != request.topology.sha256
            or metadata.get("reference_structure_sha256")
            != (
                request.reference_structure.sha256
                if request.reference_structure is not None
                else None
            )
            or metadata.get("atom_masses_sha256")
            != (request.atom_masses.sha256 if request.atom_masses is not None else None)
        ):
            raise MDAnalysisPlanError("worker source hashes or trajectory dimensions differ")
        by_name: dict[str, dict[str, object]] = {}
        for item in reported_metrics:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise MDAnalysisPlanError("worker metric entry is malformed")
            name = cast(str, item["name"])
            if name in by_name:
                raise MDAnalysisPlanError("worker returned duplicate metric names")
            by_name[name] = item
        expected_labels = {_METRIC_LABELS[metric][0] for metric in request.metrics}
        if set(by_name) != expected_labels or set(metric_artifacts) != expected_labels:
            raise MDAnalysisPlanError("worker and registered metric artifacts differ from request")
        normalized: list[MetricSeries] = []
        for metric in request.metrics:
            name, unit = _METRIC_LABELS[metric]
            entry = by_name[name]
            artifact = metric_artifacts[name]
            if artifact.sha256 is None or entry.get("sha256") != artifact.sha256:
                raise MDAnalysisPlanError(f"registered hash differs for metric {name}")
            summary_raw = entry.get("summary")
            if not isinstance(summary_raw, dict):
                raise MDAnalysisPlanError(f"summary for {name} is malformed")
            summary: dict[str, float] = {}
            for key, value in summary_raw.items():
                if (
                    not isinstance(key, str)
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    raise MDAnalysisPlanError(f"summary statistic for {name} is invalid")
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise MDAnalysisPlanError(f"summary statistic for {name} is non-finite")
                summary[key] = numeric
            selection_key = {
                TrajectoryMetric.BACKBONE_RMSD: "backbone",
                TrajectoryMetric.LIGAND_POSE_RMSD: "ligand",
                TrajectoryMetric.LIGAND_INTERNAL_RMSD: "ligand",
                TrajectoryMetric.PROTEIN_CA_RMSF: "protein_ca",
                TrajectoryMetric.PROTEIN_RADIUS_OF_GYRATION: "protein",
                TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE: "ligand",
                TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT: "ligand",
            }[metric]
            fit_selection: str | None = None
            refit: bool | None = None
            if metric is TrajectoryMetric.BACKBONE_RMSD:
                fit_selection = request.selections["backbone"].description
                refit = True
            elif metric is TrajectoryMetric.LIGAND_POSE_RMSD:
                if request.pose_fit_selection is None:
                    raise MDAnalysisPlanError("pose RMSD request has no fit selection")
                fit_selection = request.pose_fit_selection.description
                refit = False
            elif metric is TrajectoryMetric.LIGAND_INTERNAL_RMSD:
                fit_selection = request.selections["ligand"].description
                refit = True
            elif metric is TrajectoryMetric.PROTEIN_CA_RMSF:
                fit_selection = request.selections["protein_ca"].description
                refit = True
            weighting = (
                request.rmsd_weighting
                if metric
                in {
                    TrajectoryMetric.BACKBONE_RMSD,
                    TrajectoryMetric.LIGAND_POSE_RMSD,
                    TrajectoryMetric.LIGAND_INTERNAL_RMSD,
                }
                else None
            )
            notes: str | None = None
            if metric is TrajectoryMetric.LIGAND_POSE_RMSD:
                notes = (
                    "Coordinates were prealigned by the linked processing result; "
                    "this metric does not re-fit the ligand."
                )
            elif metric in {
                TrajectoryMetric.PROTEIN_LIGAND_MIN_DISTANCE,
                TrajectoryMetric.PROTEIN_LIGAND_CONTACT_COUNT,
            }:
                notes = (
                    "Cartesian distances after the linked no-jump, whole-molecule and "
                    "alignment transforms; box vectors are not applied after fitting."
                    if TrajectoryTransform.ALIGN_ROT_TRANS in preprocessing.transforms
                    else "Minimum-image periodic distances from the trajectory box."
                )
            normalized.append(
                MetricSeries(
                    name=name,
                    definition=MetricDefinition(
                        target_selection=request.selections[selection_key].description,
                        fit_selection=fit_selection,
                        refit=refit,
                        weighting=weighting,
                        notes=notes,
                    ),
                    unit=unit,
                    axis="residue" if metric is TrajectoryMetric.PROTEIN_CA_RMSF else "time_ns",
                    value_column="value",
                    series=artifact,
                    summary=summary,
                    window_ns=(request.start_time_ns, request.end_time_ns),
                )
            )
        software_version = metadata.get("mdanalysis_version")
        if not isinstance(software_version, str) or not software_version:
            raise MDAnalysisPlanError("worker did not report its MDAnalysis version")
        expected_sources = {request.trajectory.artifact_id, request.topology.artifact_id}
        if request.reference_structure is not None:
            expected_sources.add(request.reference_structure.artifact_id)
        if request.atom_masses is not None:
            expected_sources.add(request.atom_masses.artifact_id)
        if not expected_sources.issubset({item.artifact_id for item in source_artifacts.values()}):
            raise MDAnalysisPlanError("normalized source artifact registry omitted a request input")
        engine_artifacts = engine_artifacts or {}
        if raw_result_artifact.sha256 is None or any(
            artifact.sha256 is None
            for artifact in (
                *source_artifacts.values(),
                *engine_artifacts.values(),
                *log_artifacts.values(),
            )
        ):
            raise MDAnalysisPlanError("result, input, and log artifacts must be hash-linked")
        return TrajectoryAnalysisResult(
            id=new_ulid(),
            request_id=request.id,
            simulation_id=request.simulation_id,
            trajectory_id=request.trajectory_id,
            preprocessing_result_id=preprocessing.id,
            analyzer=SoftwareRef(
                name="MDAnalysis",
                version=software_version,
                kind=SoftwareKind.LIBRARY,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
            parameters=cast(
                dict[str, JsonValue],
                {
                    "metrics": [metric.value for metric in request.metrics],
                    "reference_frame": request.reference_frame,
                    "start_time_ns": request.start_time_ns,
                    "end_time_ns": request.end_time_ns,
                    "stride": request.stride,
                    "contact_cutoff_A": request.contact_cutoff_A,
                    "rmsd_weighting": request.rmsd_weighting,
                    "distance_mode": (
                        "cartesian_unwrapped"
                        if TrajectoryTransform.ALIGN_ROT_TRANS in preprocessing.transforms
                        else "minimum_image"
                    ),
                    "selections": {
                        key: value.description for key, value in request.selections.items()
                    },
                },
            ),
            source_artifacts=source_artifacts,
            raw_result=raw_result_artifact,
            engine_artifacts=engine_artifacts,
            log_artifacts=log_artifacts,
            metrics=tuple(normalized),
        )
