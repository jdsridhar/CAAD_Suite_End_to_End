"""Read-only traversal of persisted attempt/artifact provenance ancestry."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.storage.models import (
    ArtifactRow,
    AttemptArtifactRow,
    ProjectRow,
    TaskAttemptRow,
    TaskRow,
    WorkflowRunRow,
)


class ProvenanceNodeNotFound(LookupError):
    """The requested attempt, run, or project is absent from the provenance store."""


def attempt_lineage(sessions: sessionmaker[Session], attempt_id: str) -> dict[str, Any]:
    """Return the requested attempt and recursively linked producer attempts."""
    return _collect_lineage(sessions, (attempt_id,), root_attempt_id=attempt_id)


def run_lineage(
    sessions: sessionmaker[Session],
    *,
    run_id: str | None = None,
    attempt_ids: tuple[str, ...] | None = None,
    root_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Return provenance for all attempts in one run, or explicitly selected attempts."""
    if attempt_ids is not None:
        roots = attempt_ids
    elif run_id is not None:
        with sessions() as session:
            run = session.get(WorkflowRunRow, run_id)
            if run is None:
                raise ProvenanceNodeNotFound(f"workflow run {run_id!r} was not found")
            roots = tuple(
                session.scalars(
                    select(TaskAttemptRow.id)
                    .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                    .where(TaskRow.run_id == run_id)
                ).all()
            )
    else:
        raise ValueError("provide run_id or attempt_ids")
    graph = _collect_lineage(sessions, roots, root_attempt_id=root_attempt_id)
    if run_id is not None:
        graph["run_id"] = run_id
    return graph


def project_lineage(sessions: sessionmaker[Session], *, project_id: str) -> dict[str, Any]:
    """Return merged provenance from every run belonging to a project."""
    with sessions() as session:
        if session.get(ProjectRow, project_id) is None:
            raise ProvenanceNodeNotFound(f"project {project_id!r} was not found")
        run_ids = tuple(
            session.scalars(
                select(WorkflowRunRow.id).where(WorkflowRunRow.project_id == project_id)
            ).all()
        )
    graphs = [run_lineage(sessions, run_id=item) for item in run_ids]
    attempts = {row["id"]: row for graph in graphs for row in graph["attempts"]}
    artifacts = {row["id"]: row for graph in graphs for row in graph["artifacts"]}
    edges = {
        (row["attempt_id"], row["artifact_id"], row["direction"], row["role"])
        for graph in graphs
        for row in graph["edges"]
    }
    result = _graph_payload(None, attempts, artifacts, edges)
    result["project_id"] = project_id
    result["run_ids"] = list(run_ids)
    return result


def _collect_lineage(
    sessions: sessionmaker[Session], roots: tuple[str, ...], *, root_attempt_id: str | None
) -> dict[str, Any]:
    attempts: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str, str]] = set()
    pending = deque(roots)
    with sessions() as session:
        if roots and session.get(TaskAttemptRow, roots[0]) is None:
            raise ProvenanceNodeNotFound(f"task attempt {roots[0]!r} was not found")
        while pending:
            current_id = pending.popleft()
            if current_id in attempts:
                continue
            current = session.get(TaskAttemptRow, current_id)
            if current is None:
                continue
            task = session.get(TaskRow, current.task_id)
            attempts[current_id] = {
                "id": current.id,
                "task_id": current.task_id,
                "stage_id": task.stage_id if task else None,
                "attempt_no": current.attempt_no,
                "status": current.exit_status,
                "started_at": _iso(current.started_at),
                "ended_at": _iso(current.ended_at),
                "payload": current.payload,
            }
            links = session.scalars(
                select(AttemptArtifactRow).where(AttemptArtifactRow.attempt_id == current_id)
            ).all()
            for link in links:
                artifact = session.get(ArtifactRow, link.artifact_id)
                if artifact is None:
                    continue
                artifacts[artifact.id] = {
                    "id": artifact.id,
                    "sha256": artifact.sha256,
                    "kind": artifact.kind,
                    "media_type": artifact.media_type,
                    "size_bytes": artifact.size_bytes,
                    "producer_attempt_id": artifact.producer_attempt_id,
                }
                edges.add((current_id, artifact.id, link.direction, link.role))
                if link.direction == "used" and artifact.producer_attempt_id:
                    pending.append(artifact.producer_attempt_id)
    return _graph_payload(root_attempt_id, attempts, artifacts, edges)


def _graph_payload(
    root_id: str | None,
    attempts: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    edges: set[tuple[str, str, str, str]],
) -> dict[str, Any]:
    return {
        "root_attempt_id": root_id,
        "attempts": sorted(attempts.values(), key=lambda x: (x["started_at"] or "", x["id"])),
        "artifacts": sorted(artifacts.values(), key=lambda x: x["id"]),
        "edges": [
            {"attempt_id": a, "artifact_id": f, "direction": d, "role": r}
            for a, f, d, r in sorted(edges)
        ],
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
