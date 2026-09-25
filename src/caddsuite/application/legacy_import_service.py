"""Import legacy projects as an explicit, provenance-partial workflow activity."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import caddsuite
from caddsuite.application.legacy_import import LegacyImportPlan, LegacyKind, plan_legacy_import
from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.execution import (
    AttemptArtifact,
    AttemptSoftware,
    AttemptStatus,
    TaskAttempt,
)
from caddsuite.contracts.legacy import LegacyImportedFile, LegacyImportReport, LegacyOmittedFile
from caddsuite.domain.enums import LicenseClass, SoftwareKind, TaskState
from caddsuite.domain.identity import new_ulid
from caddsuite.provenance.host import capture_host_info
from caddsuite.provenance.software import platform_ref
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.attempts import TaskAttemptStore
from caddsuite.storage.models import (
    ArtifactRow,
    ProjectRow,
    TaskAttemptRow,
    TaskRow,
    WorkflowRunRow,
)
from caddsuite.storage.task_state import TaskStateStore


class LegacyImportConflict(RuntimeError):
    """The same legacy project has a previous import run that is not complete."""


@dataclass(frozen=True, slots=True)
class LegacyImportExecution:
    project_id: str
    run_id: str
    task_attempt_id: str
    report: LegacyImportReport
    already_imported: bool


def import_legacy_project(
    source_root: Path,
    *,
    kind: LegacyKind,
    sessions: sessionmaker[Session],
    artifacts: ArtifactStore,
    max_file_bytes: int = 32 * 1024 * 1024,
    max_total_bytes: int = 256 * 1024 * 1024,
) -> LegacyImportExecution:
    """Copy validated bounded artifacts, write a normalized report and provenance activity."""
    plan = plan_legacy_import(
        source_root,
        kind=kind,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )
    slug = _project_slug(plan)
    config_hash = _import_config_hash(max_file_bytes, max_total_bytes)
    accession = f"LEGACY-{plan.manifest_sha256[:10]}-{config_hash[:8]}"
    existing = _existing_import(sessions, artifacts, slug, accession)
    if existing is not None:
        return existing

    refs: list[LegacyImportedFile] = []
    with sessions.begin() as session:
        for item in plan.files:
            unresolved = plan.source_root / item.relative_path
            if unresolved.is_symlink():
                raise ValueError(
                    f"legacy artifact became a symlink during import: {item.relative_path}"
                )
            source = unresolved.resolve(strict=True)
            if not source.is_relative_to(plan.source_root):
                raise ValueError(f"legacy artifact path escaped source root: {item.relative_path}")
            blob = artifacts.put_file(source)
            if blob.sha256 != item.sha256 or blob.size_bytes != item.size_bytes:
                raise ValueError(
                    f"legacy artifact changed while being imported: {item.relative_path}"
                )
            row = register_blob(
                session,
                blob,
                kind=f"legacy_{kind}_{item.category}",
                media_type=_media_type(source),
                original_name=source.name,
            )
            refs.append(
                LegacyImportedFile(
                    relative_path=item.relative_path,
                    size_bytes=item.size_bytes,
                    sha256=item.sha256,
                    category=item.category,
                    artifact=ArtifactRef(
                        artifact_id=row.id, role=f"legacy_file_{len(refs):04d}", sha256=row.sha256
                    ),
                )
            )

    now = datetime.now(UTC)
    report = LegacyImportReport(
        id=new_ulid(),
        source_kind=kind,
        source_name=plan.source_name,
        source_root=str(plan.source_root),
        source_manifest_sha256=plan.manifest_sha256,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        imported_at=now,
        metadata=plan.metadata,
        imported_files=tuple(refs),
        omitted_files=tuple(
            LegacyOmittedFile(
                relative_path=item.relative_path, size_bytes=item.size_bytes, reason=item.reason
            )
            for item in plan.omitted
        ),
    )
    report_blob = artifacts.put_bytes(report.model_dump_json(indent=2).encode("utf-8"))
    with sessions.begin() as session:
        project = session.scalar(select(ProjectRow).where(ProjectRow.slug == slug))
        if project is None:
            project = ProjectRow(
                slug=slug,
                name=f"Legacy {plan.source_name}",
                description=(
                    f"Imported from legacy {kind} project. Historical scientific provenance "
                    "is partial; see the LegacyImportReport artifact."
                ),
            )
            session.add(project)
            session.flush()
        run = WorkflowRunRow(
            project_id=project.id,
            accession=accession,
            workflow_hash=plan.manifest_sha256,
            config_hash=config_hash,
            status="running",
            started_at=now,
        )
        session.add(run)
        session.flush()
        project_id, run_id = project.id, run.id

    task_store = TaskStateStore(sessions)
    task = task_store.create(run_id=run_id, stage_id="legacy_import")
    task = task_store.transition(
        task.id,
        expected=task.state,
        target=TaskState.READY,
        expected_version=task.version,
        reason="validated legacy project inventory",
    )
    task = task_store.transition(
        task.id,
        expected=task.state,
        target=TaskState.RUNNING,
        expected_version=task.version,
        reason="importing artifacts into the content-addressed store",
    )
    stored_attempts = TaskAttemptStore(sessions)
    attempt = TaskAttempt(
        id=new_ulid(),
        task_id=task.id,
        attempt_no=stored_attempts.next_attempt_no(task.id),
        executor="local",
        host=capture_host_info(),
        platform=platform_ref(),
        software=(
            AttemptSoftware(
                role="adapter",
                software=SoftwareRef(
                    name=f"CADD Suite {kind} legacy importer",
                    version=caddsuite.__version__,
                    kind=SoftwareKind.ADAPTER,
                    license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
                ),
            ),
        ),
        parameters={
            "source_kind": kind,
            "source_name": plan.source_name,
            "source_manifest_sha256": plan.manifest_sha256,
            "selected_artifact_count": len(refs),
            "omitted_artifact_count": len(plan.omitted),
            "import_policy": report.import_policy,
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
        },
        artifacts=tuple(
            AttemptArtifact(artifact=item.artifact, direction="used", role=item.artifact.role)
            for item in refs
        ),
        started_at=now,
        status=AttemptStatus.RUNNING,
    )
    attempt = stored_attempts.begin(attempt)
    with sessions.begin() as session:
        report_row = register_blob(
            session,
            report_blob,
            kind="legacy_import_report",
            media_type="application/json",
            original_name=f"{plan.source_name}_legacy_import.json",
            producer_attempt_id=str(attempt.id),
        )
        report_ref = ArtifactRef(
            artifact_id=report_row.id,
            role="legacy_import_report",
            sha256=report_row.sha256,
        )
    stored_attempts.finish(
        str(attempt.id),
        status=AttemptStatus.SUCCEEDED,
        ended_at=datetime.now(UTC),
        steps=(),
        generated_artifacts=(
            AttemptArtifact(
                artifact=report_ref, direction="generated", role="normalized_import_report"
            ),
        ),
    )
    task_store.transition(
        task.id,
        expected=TaskState.RUNNING,
        target=TaskState.SUCCEEDED,
        expected_version=task.version,
        reason="legacy project import report stored",
    )
    with sessions.begin() as session:
        stored_run = session.get(WorkflowRunRow, run_id)
        if stored_run is None:
            raise RuntimeError("workflow run disappeared while finalizing the legacy import")
        stored_run.status = "succeeded"
        stored_run.finished_at = datetime.now(UTC)
    return LegacyImportExecution(project_id, run_id, str(attempt.id), report, False)


def _existing_import(
    sessions: sessionmaker[Session], artifacts: ArtifactStore, slug: str, accession: str
) -> LegacyImportExecution | None:
    with sessions() as session:
        project = session.scalar(select(ProjectRow).where(ProjectRow.slug == slug))
        if project is None:
            return None
        run = session.scalar(
            select(WorkflowRunRow).where(
                WorkflowRunRow.project_id == project.id,
                WorkflowRunRow.accession == accession,
            )
        )
        if run is None:
            return None
        if run.status != "succeeded":
            raise LegacyImportConflict(
                f"legacy import {accession} exists with status {run.status!r}; inspect before retry"
            )
        row = session.scalar(
            select(TaskAttemptRow)
            .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
            .where(TaskRow.run_id == run.id)
        )
        if row is None or row.payload is None:
            raise LegacyImportConflict(f"legacy import {accession} has no attempt provenance")
        report_link = next(
            (
                edge
                for edge in row.payload.get("artifacts", [])
                if edge.get("direction") == "generated"
                and edge.get("role") == "normalized_import_report"
            ),
            None,
        )
        if report_link is None:
            raise LegacyImportConflict(f"legacy import {accession} has no report artifact")
        artifact = session.get(ArtifactRow, str(report_link["artifact"]["artifact_id"]))
        if artifact is None:
            raise LegacyImportConflict(f"legacy import {accession} report artifact is unregistered")
        if not artifacts.verify(artifact.sha256):
            raise LegacyImportConflict(f"legacy import {accession} report artifact hash failed")
        with artifacts.open(artifact.sha256) as stream:
            report = LegacyImportReport.model_validate_json(stream.read())
        return LegacyImportExecution(project.id, run.id, row.id, report, True)


def _project_slug(plan: LegacyImportPlan) -> str:
    safe_name = re.sub(r"[^a-z0-9]+", "-", plan.source_name.lower()).strip("-")[:32] or "project"
    path_hash = hashlib.sha256(str(plan.source_root).encode()).hexdigest()[:10]
    return f"legacy-{plan.kind}-{safe_name}-{path_hash}"[:63]


def _import_config_hash(max_file_bytes: int, max_total_bytes: int) -> str:
    payload = json.dumps(
        {
            "policy": "bounded_allowlist_v1",
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _media_type(path: Path) -> str:
    by_suffix = {
        ".csv": "text/csv",
        ".log": "text/plain",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".conf": "text/plain",
        ".mdp": "text/plain",
        ".top": "text/plain",
        ".itp": "text/plain",
        ".ndx": "text/plain",
        ".pdb": "chemical/x-pdb",
        ".pdbqt": "chemical/x-pdbqt",
        ".sdf": "chemical/x-mdl-sdfile",
        ".mol2": "chemical/x-mol2",
        ".json": "application/json",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".png": "image/png",
        ".gro": "chemical/x-gromacs-gro",
        ".psf": "chemical/x-psf",
        ".crd": "chemical/x-charmm-crd",
        ".par": "text/plain",
        ".rtf": "text/plain",
        ".dat": "text/plain",
        ".xvg": "text/plain",
    }
    return by_suffix.get(path.suffix.lower(), "application/octet-stream")
