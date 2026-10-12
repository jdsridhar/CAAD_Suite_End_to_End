"""Present recorded, hash-verified trajectory metrics without recomputing the science."""

from __future__ import annotations

import csv
import math
from typing import cast

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.analysis import MetricSeries, TrajectoryAnalysisResult
from caddsuite.contracts.base import load_contract
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
        for cached, task in rows:
            try:
                result = load_contract(cached.payload)
            except (TypeError, ValueError):
                continue
            if not isinstance(result, TrajectoryAnalysisResult):
                continue
            source_top = result.source_artifacts.get("topology")
            source_traj = result.source_artifacts.get("trajectory")
            if (
                source_top is None
                or source_traj is None
                or source_top.sha256 != topology.sha256
                or source_traj.sha256 != trajectory.sha256
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
