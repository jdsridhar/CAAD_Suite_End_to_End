"""Browser trajectory choices derived from completed MD result provenance."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import cast

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from caddsuite.contracts.base import load_contract
from caddsuite.contracts.md import MDStageResult
from caddsuite.storage.models import (
    ArtifactRow,
    AttemptArtifactRow,
    ProjectArtifactRow,
    TaskAttemptRow,
    TaskCacheRow,
    TaskRow,
    WorkflowRunRow,
)

_STRUCTURES = (".gro", ".pdb", ".mmcif", ".cif", ".psf", ".prmtop")
_TRAJECTORIES = (".xtc", ".trr", ".dcd", ".nc", ".netcdf", ".lammpstrj", ".dump")


def recorded_trajectory_options(session: Session, project_id: str) -> list[dict[str, JsonValue]]:
    """Offer a structure and trajectories belonging to the same successful MD task.

    Filenames identify browser formats only; pairing comes from MDStageResult.
    GROMACS .top includes cannot replace a self-contained structure in the viewer.
    Full artifact verification still belongs to download/analysis execution.
    """
    visible_ids = set(
        session.scalars(
            select(ProjectArtifactRow.artifact_id).where(
                ProjectArtifactRow.project_id == project_id
            )
        )
    )
    visible_ids.update(
        session.scalars(
            select(AttemptArtifactRow.artifact_id)
            .join(TaskAttemptRow, TaskAttemptRow.id == AttemptArtifactRow.attempt_id)
            .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
            .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
            .where(WorkflowRunRow.project_id == project_id)
        )
    )
    rows = session.execute(
        select(TaskCacheRow, TaskRow, WorkflowRunRow)
        .join(TaskRow, TaskRow.cache_key == TaskCacheRow.cache_key)
        .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
        .where(
            WorkflowRunRow.project_id == project_id,
            TaskRow.state.in_(("succeeded", "succeeded_with_warnings", "cached")),
            TaskCacheRow.schema_version.like("md_stage_result/%"),
        )
        .order_by(TaskRow.updated_at.desc(), TaskRow.id.desc())
    )
    options: list[dict[str, JsonValue]] = []
    for cached, task, run in rows:
        try:
            result = load_contract(cached.payload)
        except (TypeError, ValueError):
            continue
        if not isinstance(result, MDStageResult):
            continue
        candidates: list[ArtifactRow] = []
        seen: set[tuple[str, str]] = set()
        for ref in result.artifacts.values():
            if ref.artifact_id not in visible_ids:
                continue
            artifact = session.get(ArtifactRow, ref.artifact_id)
            if artifact is None or artifact.sha256 != ref.sha256:
                continue
            extension = PurePosixPath(artifact.original_name or "").suffix.lower()
            key = (artifact.sha256, extension)
            if key not in seen:
                candidates.append(artifact)
                seen.add(key)
        structures = sorted(
            (a for a in candidates if _extension(a) in _STRUCTURES),
            key=lambda a: (_STRUCTURES.index(_extension(a)), a.id),
        )
        trajectories = sorted(
            (a for a in candidates if _extension(a) in _TRAJECTORIES),
            key=lambda a: (_TRAJECTORIES.index(_extension(a)), a.id),
        )
        if not structures or not trajectories:
            continue
        options.append(
            {
                "task_id": task.id,
                "run_id": run.id,
                "accession": run.accession,
                "stage_id": task.stage_id,
                "stage_kind": result.stage_kind.value,
                "system_id": str(result.system_id),
                "topologies": cast(JsonValue, [_artifact_view(structures[0])]),
                "trajectories": cast(JsonValue, [_artifact_view(a) for a in trajectories]),
            }
        )
    return options


def _extension(artifact: ArtifactRow) -> str:
    return PurePosixPath(artifact.original_name or "").suffix.lower()


def _artifact_view(artifact: ArtifactRow) -> dict[str, JsonValue]:
    return {
        "id": artifact.id,
        "sha256": artifact.sha256,
        "original_name": artifact.original_name,
        "kind": artifact.kind,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
    }
