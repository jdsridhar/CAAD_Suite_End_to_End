"""Read-only traversal of persisted attempt/artifact provenance ancestry."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.storage.models import ArtifactRow, AttemptArtifactRow, TaskAttemptRow, TaskRow


class ProvenanceNodeNotFound(LookupError):
    """The requested attempt is absent from the provenance store."""


def attempt_lineage(sessions: sessionmaker[Session], attempt_id: str) -> dict[str, Any]:
    """Return a JSON-safe graph by following used artifacts to producer attempts."""
    with sessions() as session:
        if session.get(TaskAttemptRow, attempt_id) is None:
            raise ProvenanceNodeNotFound(f"task attempt {attempt_id!r} was not found")
        attempts: dict[str, dict[str, Any]] = {}
        artifacts: dict[str, dict[str, Any]] = {}
        edges: set[tuple[str, str, str, str]] = set()
        pending = deque([attempt_id])
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
        return {
            "root_attempt_id": attempt_id,
            "attempts": sorted(attempts.values(), key=lambda x: (x["started_at"] or "", x["id"])),
            "artifacts": sorted(artifacts.values(), key=lambda x: x["id"]),
            "edges": [
                {"attempt_id": a, "artifact_id": f, "direction": d, "role": r}
                for a, f, d, r in sorted(edges)
            ],
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
