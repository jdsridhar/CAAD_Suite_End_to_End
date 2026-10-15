"""Present recorded, hash-verified trajectory metrics without recomputing the science."""

from __future__ import annotations

import csv
import math
from typing import cast

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.analysis import (
    MetricSeries,
    TrajectoryAnalysisResult,
    TrajectoryProcessingResult,
)
from caddsuite.contracts.base import VersionedContract, load_contract
from caddsuite.contracts.md import MDStageResult
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.models import (
    ArtifactRow,
    AttemptArtifactRow,
    ProjectArtifactRow,
    ProjectRow,
    TaskAttemptRow,
    TaskCacheRow,
    TaskRow,
    WorkflowRunRow,
)


class RecordedAnalysisUnavailable(ValueError):
    """The selected inputs have no readable, completed workflow analysis."""


def _matches_recorded_inputs(
    result: TrajectoryAnalysisResult,
    topology_sha: str,
    trajectory_sha: str,
    contracts: list[VersionedContract],
) -> bool:
    source_top = result.source_artifacts.get("topology")
    source_traj = result.source_artifacts.get("trajectory")
    if source_top is None or source_traj is None:
        return False
    if (source_top.sha256, source_traj.sha256) == (topology_sha, trajectory_sha):
        return True
    parent = next(
        (
            item
            for item in contracts
            if isinstance(item, TrajectoryProcessingResult)
            and item.id == result.preprocessing_result_id
        ),
        None,
    )
    if parent is None or parent.simulation_id != result.simulation_id:
        return False
    if source_top != parent.reference_structure or source_traj != parent.output_artifacts.get(
        "processed"
    ):
        return False
    raw_hashes = {ref.sha256 for ref in parent.source_artifacts.values()}
    if trajectory_sha not in raw_hashes:
        return False
    if topology_sha in raw_hashes:
        return True
    # A browser GRO model and processing TPR may be separate outputs of the same
    # successful MD task. Prove the chain through that result, never through names.
    processing_topology = parent.source_artifacts.get("topology")
    if processing_topology is None:
        return False
    for source in contracts:
        if not isinstance(source, MDStageResult):
            continue
        refs = tuple(source.artifacts.values())
        hashes = {ref.sha256 for ref in refs}
        if topology_sha in hashes and trajectory_sha in hashes and processing_topology in refs:
            return True
    return False


def _visible_artifact(session: Session, project_id: str, artifact_id: str) -> ArtifactRow:
    row = session.get(ArtifactRow, artifact_id)
    uploaded = session.scalar(
        select(ProjectArtifactRow.artifact_id).where(
            ProjectArtifactRow.project_id == project_id,
            ProjectArtifactRow.artifact_id == artifact_id,
        )
    )
    generated = session.scalar(
        select(AttemptArtifactRow.artifact_id)
        .join(TaskAttemptRow, TaskAttemptRow.id == AttemptArtifactRow.attempt_id)
        .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
        .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
        .where(
            WorkflowRunRow.project_id == project_id,
            AttemptArtifactRow.artifact_id == artifact_id,
        )
    )
    if row is None or (uploaded is None and generated is None):
        raise KeyError("Selected artifact was not found in this project.")
    return row


def _metric_view(metric: MetricSeries, store: ArtifactStore) -> dict[str, JsonValue]:
    digest = metric.series.sha256
    if digest is None or not store.verify(digest):
        raise RecordedAnalysisUnavailable(f"Metric {metric.name} has missing or changed data.")
    path = store.path_for(digest)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise RecordedAnalysisUnavailable(
            f"Metric {metric.name} exceeds the preview limit; download its recorded CSV."
        )
    x: list[float] = []
    values: list[float] = []
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {metric.axis, metric.value_column}.issubset(
            reader.fieldnames
        ):
            raise RecordedAnalysisUnavailable(f"Metric {metric.name} has invalid CSV columns.")
        try:
            for row in reader:
                point, value = float(row[metric.axis]), float(row[metric.value_column])
                if not math.isfinite(point) or not math.isfinite(value):
                    raise ValueError("non-finite metric")
                x.append(point)
                values.append(value)
                if len(values) > 100_000:
                    raise RecordedAnalysisUnavailable(
                        f"Metric {metric.name} exceeds the preview limit; download its CSV."
                    )
        except (TypeError, ValueError, KeyError) as exc:
            raise RecordedAnalysisUnavailable(
                f"Metric {metric.name} contains invalid data."
            ) from exc
    if not values:
        raise RecordedAnalysisUnavailable(f"Metric {metric.name} contains no measurements.")
    return {
        "name": metric.name,
        "unit": metric.unit,
        "axis": metric.axis,
        "x": cast(JsonValue, x),
        "values": cast(JsonValue, values),
        "definition": metric.definition.model_dump(mode="json"),
        "summary": cast(JsonValue, metric.summary),
        "artifact_id": str(metric.series.artifact_id),
        "sha256": digest,
        "window_ns": list(metric.window_ns),
    }


def load_recorded_trajectory_analytics(
    project_id: str,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
    *,
    topology_artifact_id: str,
    trajectory_artifact_id: str,
) -> dict[str, JsonValue]:
    """Select exact input hashes from completed project tasks; never infer a file pairing."""
    with sessions() as session:
        if session.get(ProjectRow, project_id) is None:
            raise KeyError("Project was not found.")
        topology = _visible_artifact(session, project_id, topology_artifact_id)
        trajectory = _visible_artifact(session, project_id, trajectory_artifact_id)
        for artifact in (topology, trajectory):
            if not store.verify(artifact.sha256):
                raise RecordedAnalysisUnavailable("A selected input is missing or has changed.")
        rows = session.execute(
            select(TaskCacheRow, TaskRow)
            .join(TaskRow, TaskRow.cache_key == TaskCacheRow.cache_key)
            .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
            .where(
                WorkflowRunRow.project_id == project_id,
                TaskRow.state.in_(("succeeded", "succeeded_with_warnings", "cached")),
            )
            .order_by(TaskCacheRow.created_at.desc(), TaskCacheRow.cache_key.desc())
        )
        completed: list[tuple[VersionedContract, TaskRow]] = []
        for cached, task in rows:
            try:
                result = load_contract(cached.payload)
            except (TypeError, ValueError):
                continue
            completed.append((result, task))
        for result, task in completed:
            if not isinstance(result, TrajectoryAnalysisResult):
                continue
            if not _matches_recorded_inputs(
                result, topology.sha256, trajectory.sha256, [item for item, _ in completed]
            ):
                continue
            metrics = [_metric_view(metric, store) for metric in result.metrics]
            if not metrics:
                raise RecordedAnalysisUnavailable("This workflow recorded no trajectory metrics.")
            return {
                "status": "recorded",
                "result_id": str(result.id),
                "task_id": str(task.id),
                "run_id": str(task.run_id),
                "analyzer": result.analyzer.model_dump(mode="json"),
                "parameters": cast(JsonValue, result.parameters),
                "metrics": cast(JsonValue, metrics),
                "warnings": [
                    "Only recorded measurements are displayed. Metrics absent from the workflow "
                    "are unavailable; no replacement values are generated."
                ],
            }
    raise RecordedAnalysisUnavailable(
        "No completed analysis matches these exact inputs. Run a trajectory-analysis workflow "
        "with explicit selections and preprocessing, then load its recorded results here."
    )
