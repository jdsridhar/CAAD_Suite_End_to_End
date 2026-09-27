"""Persist exact CLI workflow sources as project-owned artifacts for later export."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.models import ProjectArtifactRow


def capture_cli_run_sources(
    session: Session,
    *,
    artifact_store: ArtifactStore,
    project_id: str,
    run_id: str,
    workflow_file: Path,
    inputs_file: Path,
    workflow_bytes: bytes,
    input_bytes: bytes,
) -> None:
    """Store source bytes and link them to the project with run-scoped roles.

    Workflow/input hashes alone cannot reconstruct a CLI run. These immutable CAS
    artifacts preserve the exact submitted files without copying them into the
    metadata database.
    """
    sources = (
        ("workflow", workflow_file, "workflow_source", "application/yaml"),
        ("inputs", inputs_file, "input_manifest", "application/json"),
    )
    for label, path, kind, media_type in sources:
        payload = workflow_bytes if label == "workflow" else input_bytes
        blob = artifact_store.put_bytes(payload)
        artifact = register_blob(
            session,
            blob,
            kind=kind,
            media_type=media_type,
            original_name=path.name,
        )
        role = f"run_{run_id}_{label}"
        link = session.get(ProjectArtifactRow, (project_id, artifact.id, role))
        if link is None:
            session.add(
                ProjectArtifactRow(project_id=project_id, artifact_id=artifact.id, role=role)
            )
