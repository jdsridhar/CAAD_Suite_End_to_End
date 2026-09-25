"""Capture immutable Conda environment locks for engine workers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from caddsuite.application.runtime import LocalRuntimeServices
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.execution import SoftwareEnvironment
from caddsuite.provenance.software import snapshot_conda_prefix, to_software_environment
from caddsuite.storage.artifacts import register_blob


def capture_conda_environment(
    prefix: Path, services: LocalRuntimeServices
) -> SoftwareEnvironment | None:
    """Store an explicit package lock when prefix is a Conda environment."""
    if not (prefix / "conda-meta").is_dir():
        return None
    snapshot = snapshot_conda_prefix(prefix)
    blob = services.artifacts.put_bytes(snapshot.explicit_lock.encode("utf-8"))
    with services.sessions.begin() as session:
        row = register_blob(
            session,
            blob,
            kind="environment_lock",
            media_type="text/plain",
            original_name=f"{snapshot.name or prefix.name}-conda-explicit.txt",
        )
        ref = ArtifactRef(artifact_id=row.id, role="environment_lock", sha256=row.sha256)
    return to_software_environment(snapshot, datetime.now(UTC), ref)
