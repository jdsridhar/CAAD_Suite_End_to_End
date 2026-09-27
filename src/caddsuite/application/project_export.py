"""Project-scoped, integrity-checked reproducibility package export."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.storage.artifacts import ArtifactIntegrityError, ArtifactStore
from caddsuite.storage.models import (
    ArtifactRow,
    CompoundFormRow,
    CompoundInputRow,
    CompoundRow,
    ProjectArtifactRow,
    ProjectRow,
    RunSubmissionRow,
    WorkflowRunRow,
)
from caddsuite.storage.provenance_graph import ProvenanceNodeNotFound, project_lineage


class ProjectExportError(RuntimeError):
    """The requested project could not be exported without losing integrity."""


@dataclass(frozen=True, slots=True)
class ProjectExportSummary:
    project_id: str
    output: Path
    included_artifacts: int
    omitted_artifacts: int
    manifest_sha256: str


_TRAJECTORY_KINDS = frozenset({"trajectory", "md_trajectory", "trajectory_file"})
_TRAJECTORY_MEDIA_TYPES = frozenset(
    {
        "application/vnd.caddsuite.trajectory",
        "chemical/x-xtc",
        "chemical/x-trr",
    }
)


def export_project(
    sessions: sessionmaker[Session],
    *,
    artifact_store: ArtifactStore,
    project_id: str,
    output: Path,
    slim: bool = False,
) -> ProjectExportSummary:
    """Export only one project's records and verified artifacts to a new directory.

    Publication is atomic on the destination filesystem. Existing targets are never
    overwritten, and a failed export removes its temporary directory.
    """
    target = output.expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise ProjectExportError(f"export target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target = target.parent.resolve() / target.name
    if target.exists() or target.is_symlink():
        raise ProjectExportError(f"export target already exists: {target}")

    with sessions() as session:
        project = session.get(ProjectRow, project_id)
        if project is None:
            raise ProvenanceNodeNotFound(f"project {project_id!r} was not found")
        project_data: dict[str, Any] = {
            "id": project.id,
            "slug": project.slug,
            "name": project.name,
            "description": project.description,
            "created_at": project.created_at.isoformat() if project.created_at else None,
        }
        compounds = session.scalars(
            select(CompoundRow)
            .where(CompoundRow.project_id == project_id)
            .order_by(CompoundRow.accession, CompoundRow.id)
        ).all()
        compound_ids = [row.id for row in compounds]
        raw_inputs = (
            session.scalars(
                select(CompoundInputRow)
                .where(CompoundInputRow.compound_id.in_(compound_ids))
                .order_by(CompoundInputRow.created_at, CompoundInputRow.id)
            ).all()
            if compound_ids
            else []
        )
        forms = (
            session.scalars(
                select(CompoundFormRow)
                .where(CompoundFormRow.compound_id.in_(compound_ids))
                .order_by(CompoundFormRow.compound_id, CompoundFormRow.kind, CompoundFormRow.id)
            ).all()
            if compound_ids
            else []
        )
        inputs_by_compound: dict[str, list[dict[str, Any]]] = {}
        for input_row in raw_inputs:
            inputs_by_compound.setdefault(input_row.compound_id, []).append(
                {
                    "id": input_row.id,
                    "payload": input_row.payload,
                    "created_at": (
                        input_row.created_at.isoformat() if input_row.created_at else None
                    ),
                }
            )
        forms_by_compound: dict[str, list[dict[str, Any]]] = {}
        for form_row in forms:
            forms_by_compound.setdefault(form_row.compound_id, []).append(
                {
                    "id": form_row.id,
                    "kind": form_row.kind,
                    "smiles": form_row.smiles,
                    "formal_charge": form_row.formal_charge,
                    "payload": form_row.payload,
                    "created_at": (
                        form_row.created_at.isoformat() if form_row.created_at else None
                    ),
                }
            )
        project_data["compounds"] = [
            {
                "id": item.id,
                "accession": item.accession,
                "name": item.name,
                "inchikey": item.inchikey,
                "payload": item.payload,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "inputs": inputs_by_compound.get(item.id, []),
                "forms": forms_by_compound.get(item.id, []),
            }
            for item in compounds
        ]
        runs = session.scalars(
            select(WorkflowRunRow)
            .where(WorkflowRunRow.project_id == project_id)
            .order_by(WorkflowRunRow.created_at, WorkflowRunRow.id)
        ).all()
        submissions = (
            {
                row.run_id: row
                for row in session.scalars(
                    select(RunSubmissionRow).where(
                        RunSubmissionRow.run_id.in_([run.id for run in runs])
                    )
                ).all()
            }
            if runs
            else {}
        )
        project_links = session.scalars(
            select(ProjectArtifactRow).where(ProjectArtifactRow.project_id == project_id)
        ).all()
        graph = project_lineage(sessions, project_id=project_id)
        artifact_ids = {link.artifact_id for link in project_links}
        artifact_ids.update(item["id"] for item in graph["artifacts"])
        artifact_rows = (
            session.scalars(select(ArtifactRow).where(ArtifactRow.id.in_(artifact_ids))).all()
            if artifact_ids
            else []
        )
        artifact_by_id = {row.id: row for row in artifact_rows}
        missing_rows = artifact_ids - set(artifact_by_id)
        if missing_rows:
            raise ProjectExportError(
                f"artifact metadata is missing for IDs: {sorted(missing_rows)}"
            )
        role_map: dict[str, list[str]] = {}
        for link in project_links:
            role_map.setdefault(link.artifact_id, []).append(link.role)

    links_by_run_role: dict[str, dict[str, str]] = {}
    for artifact_id, roles in role_map.items():
        for role in roles:
            if role.startswith("run_") and role.endswith("_workflow"):
                run_id = role[4:-9]
                links_by_run_role.setdefault(run_id, {})["workflow_artifact_id"] = artifact_id
            elif role.startswith("run_") and role.endswith("_inputs"):
                run_id = role[4:-7]
                links_by_run_role.setdefault(run_id, {})["inputs_artifact_id"] = artifact_id

    stage_artifacts = {item["id"]: item for item in graph["artifacts"]}
    artifact_metadata: list[dict[str, Any]] = []
    included: list[ArtifactRow] = []
    omitted: list[dict[str, Any]] = []
    for row in sorted(artifact_rows, key=lambda item: (item.sha256, item.id)):
        is_trajectory = (
            row.kind.lower() in _TRAJECTORY_KINDS
            or row.media_type.lower() in _TRAJECTORY_MEDIA_TYPES
        )
        base = {
            "artifact_id": row.id,
            "sha256": row.sha256,
            "kind": row.kind,
            "media_type": row.media_type,
            "size_bytes": row.size_bytes,
            "original_name": row.original_name,
            "producer_attempt_id": row.producer_attempt_id,
            "project_roles": sorted(role_map.get(row.id, [])),
            "provenance": stage_artifacts.get(row.id),
        }
        if slim and is_trajectory:
            omitted.append({**base, "reason": "trajectory_omitted_by_slim_mode"})
        else:
            included.append(row)
            artifact_metadata.append(base)

    stage_dir = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    try:
        (stage_dir / "runs").mkdir()
        (stage_dir / "provenance").mkdir()
        payload_files: list[dict[str, Any]] = []

        def write_json(relative: str, payload: Any) -> None:
            path = stage_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (
                json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
            ).encode()
            path.write_bytes(raw)
            payload_files.append(
                {
                    "path": relative,
                    "size_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )

        write_json("project.json", project_data)
        for run in runs:
            submission = submissions.get(run.id)
            run_payload = {
                "id": run.id,
                "accession": run.accession,
                "workflow_hash": run.workflow_hash,
                "config_hash": run.config_hash,
                "status": run.status,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "submission": submission.payload if submission is not None else None,
                "source_artifacts": links_by_run_role.get(run.id, {}),
                "reconstruction_complete": (
                    submission is not None
                    or {"workflow_artifact_id", "inputs_artifact_id"}
                    <= set(links_by_run_role.get(run.id, {}))
                ),
            }
            write_json(f"runs/{run.id}/run.json", run_payload)
        write_json("provenance/project.json", graph)
        write_json("artifacts/metadata.json", artifact_metadata)
        write_json("omissions.json", omitted)

        for row in included:
            source = artifact_store.path_for(row.sha256)
            if source.is_symlink() or not source.is_file():
                raise ProjectExportError(
                    f"artifact blob is missing or not a regular file: {row.id}"
                )
            if not artifact_store.verify(row.sha256):
                raise ArtifactIntegrityError(f"artifact blob failed SHA-256 verification: {row.id}")
            relative = Path("artifacts") / "sha256" / row.sha256[:2] / row.sha256[2:4] / row.sha256
            destination = stage_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with artifact_store.open(row.sha256) as src, destination.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            digest = hashlib.sha256()
            size = 0
            with destination.open("rb") as copied:
                while chunk := copied.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            if digest.hexdigest() != row.sha256 or size != row.size_bytes:
                raise ArtifactIntegrityError(f"copied artifact failed integrity check: {row.id}")
            payload_files.append(
                {"path": relative.as_posix(), "size_bytes": size, "sha256": row.sha256}
            )
            if row.kind == "environment_lock":
                lock_path = stage_dir / "environments" / "locks" / f"{row.sha256}.txt"
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(destination, lock_path)
                payload_files.append(
                    {
                        "path": lock_path.relative_to(stage_dir).as_posix(),
                        "size_bytes": size,
                        "sha256": row.sha256,
                    }
                )

        payload_files.sort(key=lambda item: item["path"])
        manifest = {
            "format": "caddsuite.project-export/1",
            "project": {"id": project_id, "slug": project_data["slug"]},
            "exported_at": datetime.now(UTC).isoformat(),
            "mode": "slim" if slim else "full",
            "files": payload_files,
            "artifacts": artifact_metadata,
            "omissions": omitted,
        }
        manifest_path = stage_dir / "manifest.json"
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode()
        manifest_path.write_bytes(manifest_bytes)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        (stage_dir / "manifest.sha256").write_text(
            manifest_hash + "  manifest.json\n", encoding="ascii"
        )
        verify_export_package(stage_dir)
        if target.exists():
            raise ProjectExportError(f"export target appeared during export: {target}")
        os.replace(stage_dir, target)
        return ProjectExportSummary(
            project_id=project_id,
            output=target,
            included_artifacts=len(included),
            omitted_artifacts=len(omitted),
            manifest_sha256=manifest_hash,
        )
    except BaseException:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def verify_export_package(package: Path) -> dict[str, Any]:
    """Verify an exported package's manifest digest, inventory, path safety and bytes."""
    root = package.expanduser().resolve(strict=True)
    if package.is_symlink() or not root.is_dir():
        raise ProjectExportError("export package must be a regular directory")
    manifest_path = root / "manifest.json"
    checksum_path = root / "manifest.sha256"
    try:
        manifest_bytes = manifest_path.read_bytes()
        checksum_line = checksum_path.read_text(encoding="ascii")
    except OSError as exc:
        raise ProjectExportError(f"export package is missing its manifest/checksum: {exc}") from exc
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    if checksum_line != f"{digest}  manifest.json\n":
        raise ProjectExportError("manifest SHA-256 checksum does not match")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectExportError(f"manifest is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "caddsuite.project-export/1":
        raise ProjectExportError("unsupported project export format")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ProjectExportError("manifest file inventory must be a list")

    listed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ProjectExportError("manifest inventory entry must be an object")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if (
            not isinstance(relative, str)
            or not isinstance(expected_hash, str)
            or not isinstance(expected_size, int)
            or expected_size < 0
        ):
            raise ProjectExportError("manifest inventory entry has invalid path/hash/size")
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or pure.as_posix() != relative
            or chr(92) in relative
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ProjectExportError(f"unsafe package path in manifest: {relative!r}")
        if relative in listed:
            raise ProjectExportError(f"duplicate package path in manifest: {relative!r}")
        listed.add(relative)
        path = root.joinpath(*pure.parts)
        if path.is_symlink():
            raise ProjectExportError(f"package file is a symlink: {relative}")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ProjectExportError(f"package file is missing: {relative}") from exc
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ProjectExportError(f"package path escapes or is not a file: {relative}")
        digest_file = hashlib.sha256()
        size = 0
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest_file.update(chunk)
                size += len(chunk)
        if size != expected_size or digest_file.hexdigest() != expected_hash:
            raise ProjectExportError(f"package file failed integrity verification: {relative}")

    if [item.get("path") for item in entries] != sorted(listed):
        raise ProjectExportError("manifest file inventory is not sorted")
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ProjectExportError(f"package contains a symlink: {path.relative_to(root)}")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    expected = listed | {"manifest.json", "manifest.sha256"}
    if actual != expected:
        raise ProjectExportError("package files do not match the manifest inventory")
    return manifest
