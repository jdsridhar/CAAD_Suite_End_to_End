"""Authenticated HTTP API for local workflow execution and provenance."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, JsonValue
from sqlalchemy import select

from caddsuite.application.handlers import StageHandlerDiscoveryError, StageHandlerRegistry
from caddsuite.application.run_queue import LocalRunSupervisor, RunSubmissionQueue
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.application.version_drift import version_drift
from caddsuite.chem.standardize import (
    ChemistryDependencyError,
    InvalidStructure,
    make_compound,
    standardize_smiles,
)
from caddsuite.contracts.base import (
    ArtifactRef,
    ContractModel,
    NonEmptyStr,
    VersionedContract,
    load_contract,
)
from caddsuite.contracts.registry import InputRecord
from caddsuite.domain.enums import TaskState
from caddsuite.domain.identity import ULIDStr, new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.compound_registry import CompoundRegistry
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.decisions import DecisionStore
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import (
    ArtifactRow,
    AttemptArtifactRow,
    CompoundRow,
    DecisionRow,
    ProjectArtifactRow,
    ProjectRow,
    RunSubmissionRow,
    TaskAttemptRow,
    TaskRow,
    ValidationIssueRow,
    WorkflowRunRow,
)
from caddsuite.storage.paths import artifacts_root, database_path, resolve_data_root
from caddsuite.storage.provenance_graph import (
    ProvenanceNodeNotFound,
    project_lineage,
    run_lineage,
)
from caddsuite.validation.decisions import (
    Decision,
    DecisionRequest,
    DecisionScope,
    OptionKey,
)
from caddsuite.workflow.compiler import WorkflowCompileError
from caddsuite.workflow.definition import WorkflowDefinition

logger = logging.getLogger(__name__)

_DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_MAX_CONFIGURED_UPLOAD_BYTES = 1024 * 1024 * 1024
_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_MEDIA_TYPE_PATTERN = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
_BEARER_AUTH = HTTPBearer(auto_error=False)


class ProjectCreateRequest(ContractModel):
    slug: str
    name: str


class ProjectResponse(ContractModel):
    id: str
    slug: str
    name: str


class CompoundCreateRequest(ContractModel):
    smiles: str
    name: str


class CompoundResponse(ContractModel):
    compound: dict[str, JsonValue]
    created: bool
    input_record_id: str


class WorkflowRunSubmission(ContractModel):
    """Normalized workflow definition and contract JSON for a local API run."""

    workflow: WorkflowDefinition
    inputs: dict[str, JsonValue]


class DecisionSubmitRequest(ContractModel):
    issue_id: ULIDStr
    chosen_key: OptionKey
    decided_by: NonEmptyStr
    expected_version: Annotated[int, Field(ge=0)]
    scope: DecisionScope = DecisionScope.TASK
    rationale: str | None = None


def create_app(
    *,
    data_root: Path | None = None,
    token: str,
    allowed_origins: tuple[str, ...] = (),
    stage_registry: StageHandlerRegistry | None = None,
    max_upload_bytes: int = _DEFAULT_MAX_UPLOAD_BYTES,
) -> FastAPI:
    """Build the local workflow API; callers must provide a per-install bearer token."""
    if not token or not token.strip():
        raise ValueError("API bearer token must be configured")
    if not 1 <= max_upload_bytes <= _MAX_CONFIGURED_UPLOAD_BYTES:
        raise ValueError("max_upload_bytes must be between 1 byte and 1 GiB")
    root = resolve_data_root(data_root)
    upgrade(database_path(root))
    engine = create_db_engine(database_path(root))
    sessions = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        queue = RunSubmissionQueue(sessions)
        supervisor = LocalRunSupervisor(
            queue,
            execute_submission,
            worker_id=secrets.token_hex(16),
        )
        supervisor.start()
        app.state.run_supervisor = supervisor
        try:
            yield
        finally:
            supervisor.stop()
            engine.dispose()

    app = FastAPI(title="CADD Suite API", version="0.1.0", lifespan=lifespan)
    app.state.sessions = sessions
    app.state.allowed_origins = frozenset(allowed_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Artifact-Role",
            "X-Filename",
        ],
    )

    def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER_AUTH)] = None,
        origin: Annotated[str | None, Header()] = None,
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials, token)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        origins: frozenset[str] = app.state.allowed_origins
        if origin is not None and origin not in origins:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")

    def execute_submission(
        stable_run_id: str,
        payload: dict[str, Any],
        cancel_requested: Callable[[], bool],
    ) -> str:
        request = WorkflowRunSubmission.model_validate(payload)
        registry = stage_registry or StageHandlerRegistry.discover()
        compiled = registry.compile(request.workflow)
        parsed = _parse_workflow_inputs(request)
        artifact_store = ArtifactStore(artifacts_root(root))
        with sessions() as session:
            for reference in _artifact_refs(parsed):
                row = session.get(ArtifactRow, str(reference.artifact_id))
                if (
                    row is None
                    or (reference.sha256 is not None and reference.sha256 != row.sha256)
                    or not artifact_store.verify(row.sha256)
                ):
                    raise ValueError(
                        f"workflow input artifact {reference.artifact_id!r} is missing "
                        "or failed hash verification"
                    )
        with sessions.begin() as session:
            run = session.get(WorkflowRunRow, stable_run_id)
            if run is None:
                raise RuntimeError(f"queued workflow run {stable_run_id!r} is missing")
            run.status = "running"
            run.started_at = datetime.now(UTC)
        if cancel_requested():
            return "stopped"
        try:
            with LocalWorkflowRuntime.open(
                data_root=root,
                handlers=lambda services: registry.build_handlers(request.workflow, services),
                cancellation_check=cancel_requested,
            ) as runtime:
                outcome = runtime.run(
                    compiled,
                    run_id=stable_run_id,
                    inputs=parsed,
                    cancel_check=cancel_requested,
                )
            run_status = (
                "awaiting_decision"
                if outcome.awaiting_decision
                else "failed"
                if outcome.failures
                else "stopped"
                if outcome.stopped
                else "succeeded"
            )
            return run_status
        except Exception:
            with sessions.begin() as session:
                run = session.get(WorkflowRunRow, stable_run_id)
                if run is not None and run.status == "running":
                    run.status = "failed"
                    run.finished_at = datetime.now(UTC)
            raise

    @app.get("/v1/projects/{project_id}/runs/{run_id}/decisions")
    def list_run_decisions(
        project_id: str,
        run_id: str,
        _: None = Depends(authenticate),
    ) -> list[dict[str, object]]:
        with sessions() as session:
            run = session.scalar(
                select(WorkflowRunRow).where(
                    WorkflowRunRow.id == run_id,
                    WorkflowRunRow.project_id == project_id,
                )
            )
            if run is None:
                raise HTTPException(status_code=404, detail="workflow run was not found")
            submission = session.get(RunSubmissionRow, run_id)
            if submission is None or submission.state != "awaiting_decision":
                return []
            pending = session.execute(
                select(ValidationIssueRow, TaskRow.stage_id, TaskRow.subject_id, TaskRow.version)
                .join(TaskRow, TaskRow.id == ValidationIssueRow.task_id)
                .where(
                    TaskRow.run_id == run_id,
                    ValidationIssueRow.severity == "decision_required",
                    ~select(DecisionRow.id)
                    .where(DecisionRow.issue_id == ValidationIssueRow.id)
                    .exists(),
                )
                .order_by(ValidationIssueRow.created_at, ValidationIssueRow.id)
            ).all()
            return [
                {
                    "issue_id": issue.id,
                    "task_id": issue.task_id,
                    "stage_id": stage_id,
                    "subject_id": subject_id,
                    "task_version": version,
                    "request": issue.payload,
                }
                for issue, stage_id, subject_id, version in pending
            ]

    @app.post("/v1/projects/{project_id}/runs/{run_id}/decisions", status_code=202)
    def submit_run_decision(
        project_id: str,
        run_id: str,
        request: DecisionSubmitRequest,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        with sessions() as session:
            issue = session.scalar(
                select(ValidationIssueRow)
                .join(TaskRow, TaskRow.id == ValidationIssueRow.task_id)
                .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
                .where(
                    ValidationIssueRow.id == request.issue_id,
                    WorkflowRunRow.id == run_id,
                    WorkflowRunRow.project_id == project_id,
                    ValidationIssueRow.severity == "decision_required",
                )
            )
            if issue is None:
                raise HTTPException(status_code=404, detail="pending decision was not found")
            task = session.get(TaskRow, issue.task_id)
            submission = session.get(RunSubmissionRow, run_id)
            if (
                task is None
                or task.state != TaskState.AWAITING_DECISION.value
                or submission is None
                or submission.state != "awaiting_decision"
            ):
                raise HTTPException(
                    status_code=409,
                    detail="workflow run has not reached a resolvable awaiting-decision state",
                )
            stored_request = DecisionRequest.model_validate(issue.payload)
            task_id = task.id
        try:
            decision = Decision(
                request=stored_request,
                chosen_key=request.chosen_key,
                decided_by=request.decided_by,
                decided_at=datetime.now(UTC),
                scope=request.scope,
                rationale=request.rationale,
            )
            result = DecisionStore(sessions).submit(
                task_id,
                decision,
                expected_version=request.expected_version,
                issue_id=request.issue_id,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "decision_id": result.decision_id,
            "issue_id": result.issue_id,
            "task_id": result.task_id,
            "state": result.state.value,
            "version": result.version,
            "run_status": "queued",
        }

    @app.post(
        "/v1/projects/{project_id}/artifacts",
        status_code=201,
        description=(
            "Stream one raw artifact into the content-addressed store. "
            "The request body is limited by the configured max_upload_bytes."
        ),
    )
    async def upload_project_artifact(
        project_id: str,
        request: Request,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail=f"project {project_id!r} was not found")

        role = request.headers.get("x-artifact-role", "input")
        if not _ROLE_PATTERN.fullmatch(role):
            raise HTTPException(status_code=422, detail="X-Artifact-Role is invalid")
        media_type = request.headers.get("content-type", "application/octet-stream")
        media_type = media_type.split(";", maxsplit=1)[0].strip().lower()
        if len(media_type) > 127 or not _MEDIA_TYPE_PATTERN.fullmatch(media_type):
            raise HTTPException(status_code=422, detail="Content-Type is invalid")
        supplied_name = request.headers.get("x-filename", "upload.bin")
        filename = supplied_name.replace(chr(92), "/").rsplit("/", maxsplit=1)[-1]
        if (
            not filename
            or len(filename) > 255
            or any(ord(character) < 32 or ord(character) == 127 for character in filename)
        ):
            raise HTTPException(status_code=422, detail="X-Filename is invalid")

        size_bytes = 0
        store = ArtifactStore(artifacts_root(root))
        try:
            spool_limit = min(max_upload_bytes, 2 * 1024 * 1024)
            with tempfile.SpooledTemporaryFile(max_size=spool_limit) as spool:
                async for chunk in request.stream():
                    size_bytes += len(chunk)
                    if size_bytes > max_upload_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"artifact exceeds the {max_upload_bytes}-byte upload limit",
                        )
                    spool.write(chunk)
                if size_bytes == 0:
                    raise HTTPException(status_code=422, detail="artifact body is empty")
                spool.seek(0)
                blob = store.put_stream(spool)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("project artifact upload failed for project %s", project_id)
            raise HTTPException(status_code=400, detail="could not read artifact upload") from exc

        with sessions.begin() as session:
            artifact = register_blob(
                session,
                blob,
                kind="input",
                media_type=media_type,
                original_name=filename,
            )
            project_link = session.get(ProjectArtifactRow, (project_id, artifact.id, role))
            if project_link is None:
                session.add(
                    ProjectArtifactRow(
                        project_id=project_id,
                        artifact_id=artifact.id,
                        role=role,
                    )
                )
            reference = ArtifactRef(
                artifact_id=artifact.id,
                role=role,
                sha256=artifact.sha256,
            )
        return {
            "project_id": project_id,
            "artifact": reference.model_dump(mode="json"),
            "size_bytes": blob.size_bytes,
            "sha256": blob.sha256,
            "created": blob.created,
        }

    @app.get("/v1/projects/{project_id}/artifacts")
    def list_project_artifacts(
        project_id: str,
        _: None = Depends(authenticate),
    ) -> list[dict[str, object]]:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail="project was not found")
            rows = {
                row.id: row
                for row in session.scalars(
                    select(ArtifactRow)
                    .join(ProjectArtifactRow, ProjectArtifactRow.artifact_id == ArtifactRow.id)
                    .where(ProjectArtifactRow.project_id == project_id)
                )
            }
            generated = session.scalars(
                select(ArtifactRow)
                .join(AttemptArtifactRow, AttemptArtifactRow.artifact_id == ArtifactRow.id)
                .join(TaskAttemptRow, TaskAttemptRow.id == AttemptArtifactRow.attempt_id)
                .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
                .where(WorkflowRunRow.project_id == project_id)
            ).all()
            rows.update({row.id: row for row in generated})
            return [
                {
                    "id": row.id,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                    "media_type": row.media_type,
                    "kind": row.kind,
                    "original_name": row.original_name,
                    "created_at": row.created_at.isoformat(),
                }
                for row in sorted(rows.values(), key=lambda item: (item.created_at, item.id))
            ]

    @app.get("/v1/projects/{project_id}/artifacts/{artifact_id}/content")
    def read_project_artifact_content(
        project_id: str,
        artifact_id: str,
        _: None = Depends(authenticate),
    ) -> FileResponse:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail="project was not found")
            artifact = session.get(ArtifactRow, artifact_id)
            if artifact is None:
                raise HTTPException(status_code=404, detail="artifact was not found")
            project_upload = (
                session.scalar(
                    select(ProjectArtifactRow.project_id).where(
                        ProjectArtifactRow.project_id == project_id,
                        ProjectArtifactRow.artifact_id == artifact_id,
                    )
                )
                is not None
            )
            generated_by_project_run = (
                session.scalar(
                    select(AttemptArtifactRow.attempt_id)
                    .join(TaskAttemptRow, TaskAttemptRow.id == AttemptArtifactRow.attempt_id)
                    .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                    .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
                    .where(
                        WorkflowRunRow.project_id == project_id,
                        AttemptArtifactRow.artifact_id == artifact_id,
                    )
                )
                is not None
            )
            if not project_upload and not generated_by_project_run:
                raise HTTPException(status_code=404, detail="artifact was not found")
            digest = artifact.sha256
            media_type = artifact.media_type
        store = ArtifactStore(artifacts_root(root))
        path = store.path_for(digest)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact content was not found")
        return FileResponse(
            path,
            media_type=media_type,
            headers={
                "Cache-Control": "private, no-store",
                "ETag": f'"{digest}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/v1/projects/{project_id}/artifacts/{artifact_id}/text")
    def read_project_text_artifact(
        project_id: str,
        artifact_id: str,
        tail_bytes: Annotated[int, Query(ge=1, le=1_000_000)] = 65_536,
        _: None = Depends(authenticate),
    ) -> PlainTextResponse:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail="project was not found")
            artifact = session.get(ArtifactRow, artifact_id)
            if artifact is None or artifact.media_type != "text/plain":
                raise HTTPException(status_code=404, detail="text artifact was not found")
            project_upload = (
                session.scalar(
                    select(ProjectArtifactRow.project_id).where(
                        ProjectArtifactRow.project_id == project_id,
                        ProjectArtifactRow.artifact_id == artifact_id,
                    )
                )
                is not None
            )
            generated_by_project_run = (
                session.scalar(
                    select(AttemptArtifactRow.attempt_id)
                    .join(TaskAttemptRow, TaskAttemptRow.id == AttemptArtifactRow.attempt_id)
                    .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                    .join(WorkflowRunRow, WorkflowRunRow.id == TaskRow.run_id)
                    .where(
                        WorkflowRunRow.project_id == project_id,
                        AttemptArtifactRow.artifact_id == artifact_id,
                    )
                )
                is not None
            )
            if not project_upload and not generated_by_project_run:
                raise HTTPException(status_code=404, detail="text artifact was not found")
            digest, size_bytes = artifact.sha256, artifact.size_bytes
        with ArtifactStore(artifacts_root(root)).open(digest) as stream:
            stream.seek(max(0, size_bytes - tail_bytes))
            content = stream.read(tail_bytes).decode("utf-8", errors="replace")
        return PlainTextResponse(content)

    @app.post("/v1/projects/{project_id}/runs/{run_id}/execute", status_code=202)
    def execute_workflow(
        project_id: str,
        run_id: str,
        request: WorkflowRunSubmission,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            stable_run_id = str(ULIDStr(run_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="run_id must be a valid ULID") from exc
        try:
            registry = stage_registry or StageHandlerRegistry.discover()
            compiled = registry.compile(request.workflow)
        except StageHandlerDiscoveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, WorkflowCompileError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not compiled.tasks:
            raise HTTPException(
                status_code=422,
                detail="workflow has no enabled stages to execute",
            )
        try:
            parsed = _parse_workflow_inputs(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        workflow_payload = request.workflow.model_dump(mode="json", by_alias=True)
        request_payload = request.model_dump(mode="json", by_alias=True)
        workflow_hash = hashlib.sha256(
            json.dumps(workflow_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        config_hash = hashlib.sha256(
            json.dumps(request_payload["inputs"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        artifact_store = ArtifactStore(artifacts_root(root))
        with sessions.begin() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail=f"project {project_id!r} was not found")
            if session.get(WorkflowRunRow, stable_run_id) is not None:
                raise HTTPException(status_code=409, detail=f"run {stable_run_id!r} already exists")
            for reference in _artifact_refs(parsed):
                row = session.get(ArtifactRow, str(reference.artifact_id))
                if row is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"input artifact {reference.artifact_id!r} is not registered",
                    )
                if reference.sha256 is not None and reference.sha256 != row.sha256:
                    raise HTTPException(
                        status_code=422,
                        detail=f"input artifact {reference.artifact_id!r} hash does not match",
                    )
                if not artifact_store.verify(row.sha256):
                    raise HTTPException(
                        status_code=422,
                        detail=f"input artifact {reference.artifact_id!r} failed hash verification",
                    )
            session.add(
                WorkflowRunRow(
                    id=stable_run_id,
                    project_id=project_id,
                    accession="RUN-" + stable_run_id,
                    workflow_hash=workflow_hash,
                    config_hash=config_hash,
                    status="queued",
                )
            )
            session.flush()
            session.add(
                RunSubmissionRow(
                    run_id=stable_run_id,
                    payload=request_payload,
                    state="queued",
                    submitted_at=datetime.now(UTC),
                )
            )
        return {
            "project_id": project_id,
            "run_id": stable_run_id,
            "status": "queued",
            "status_url": f"/v1/projects/{project_id}/runs/{stable_run_id}/status",
        }

    @app.get("/v1/projects")
    def list_projects(_: None = Depends(authenticate)) -> list[ProjectResponse]:
        with sessions() as session:
            projects = session.scalars(select(ProjectRow).order_by(ProjectRow.slug)).all()
            return [ProjectResponse(id=row.id, slug=row.slug, name=row.name) for row in projects]

    @app.post("/v1/projects", status_code=201)
    def create_project(
        request: ProjectCreateRequest,
        _: None = Depends(authenticate),
    ) -> ProjectResponse:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", request.slug):
            raise HTTPException(
                status_code=422,
                detail="slug must contain lowercase letters, digits, or hyphens",
            )
        if not request.name.strip():
            raise HTTPException(status_code=422, detail="project name must not be blank")
        with sessions.begin() as session:
            if session.scalar(select(ProjectRow.id).where(ProjectRow.slug == request.slug)):
                raise HTTPException(
                    status_code=409,
                    detail=f"project slug {request.slug!r} already exists",
                )
            row = ProjectRow(slug=request.slug, name=request.name.strip())
            session.add(row)
            session.flush()
            result = ProjectResponse(id=row.id, slug=row.slug, name=row.name)
        return result

    @app.get("/v1/projects/{project_id}/compounds")
    def list_compounds(
        project_id: str,
        _: None = Depends(authenticate),
    ) -> list[dict[str, JsonValue]]:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail=f"project {project_id!r} was not found")
            rows = session.scalars(
                select(CompoundRow)
                .where(CompoundRow.project_id == project_id)
                .order_by(CompoundRow.accession)
            ).all()
            return [
                {
                    "id": row.id,
                    "accession": row.accession,
                    "name": row.name,
                    "inchikey": row.inchikey,
                    "payload": row.payload,
                }
                for row in rows
            ]

    @app.post("/v1/projects/{project_id}/compounds", status_code=201)
    def register_compound(
        project_id: str,
        request: CompoundCreateRequest,
        _: None = Depends(authenticate),
    ) -> CompoundResponse:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail=f"project {project_id!r} was not found")
        try:
            standardized = standardize_smiles(request.smiles)
        except ChemistryDependencyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except InvalidStructure as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            name = request.name.strip() or standardized.identity.canonical_smiles
            registered = CompoundRegistry(sessions).register(
                project_id=project_id,
                inchikey=standardized.identity.inchikey,
                input_record=InputRecord(
                    source="manual", original_text=request.smiles, original_name=request.name
                ),
                create_compound=lambda accession: make_compound(
                    standardized,
                    compound_id=new_ulid(),
                    project_id=project_id,
                    accession=accession,
                    name=name,
                    original_text=request.smiles,
                    source="manual",
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return CompoundResponse(
            compound=registered.compound.model_dump(mode="json"),
            created=registered.created,
            input_record_id=registered.input_record_id,
        )

    @app.get("/v1/workflows/capabilities")
    def get_workflow_capabilities(
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            snapshot = (stage_registry or StageHandlerRegistry.discover()).snapshot()
        except StageHandlerDiscoveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "plugins": [
                {"plugin_id": name, "version": version} for name, version in snapshot.plugins
            ],
            "capabilities": [
                registration.capability.model_dump(mode="json")
                for _key, registration in sorted(snapshot.registrations.items())
            ],
        }

    @app.post("/v1/workflows/plan")
    def plan_workflow(
        workflow: WorkflowDefinition,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            registry = stage_registry or StageHandlerRegistry.discover()
            compiled = registry.compile(workflow)
        except StageHandlerDiscoveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, WorkflowCompileError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "name": compiled.name,
            "task_order": list(compiled.task_order),
            "tasks": [
                {
                    "stage_id": task.stage_id,
                    "kind": task.kind,
                    "engine": task.engine,
                    "dependencies": list(task.dependencies),
                    "input_contracts": {item.name: item.contract for item in task.inputs},
                    "output_contract": task.output_contract,
                    "fanout_scope": task.for_each,
                    "gate": task.gate,
                }
                for task in compiled.tasks
            ],
        }

    @app.get("/v1/projects/{project_id}/runs")
    def list_project_runs(
        project_id: str,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        _: None = Depends(authenticate),
    ) -> list[dict[str, JsonValue]]:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail="project was not found")
            rows = session.scalars(
                select(WorkflowRunRow)
                .where(WorkflowRunRow.project_id == project_id)
                .order_by(WorkflowRunRow.created_at.desc(), WorkflowRunRow.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "run_id": run.id,
                    "accession": run.accession,
                    "status": run.status,
                    "workflow_hash": run.workflow_hash,
                    "config_hash": run.config_hash,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "created_at": run.created_at.isoformat(),
                }
                for run in rows
            ]

    @app.post("/v1/projects/{project_id}/runs/{run_id}/cancel", status_code=202)
    def cancel_project_run(
        project_id: str,
        run_id: str,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        with sessions() as session:
            run = session.scalar(
                select(WorkflowRunRow).where(
                    WorkflowRunRow.id == run_id, WorkflowRunRow.project_id == project_id
                )
            )
            if run is None:
                raise HTTPException(status_code=404, detail=f"run {run_id!r} was not found")
            if run.status in {"succeeded", "failed", "stopped", "cancelled"}:
                raise HTTPException(status_code=409, detail="workflow run is already terminal")
        if not RunSubmissionQueue(sessions).request_cancel(run_id):
            raise HTTPException(status_code=409, detail="workflow submission cannot be cancelled")
        return {
            "project_id": project_id,
            "run_id": run_id,
            "status": "cancellation_requested",
            "detail": "Cancellation takes effect at the next safe workflow boundary.",
        }

    @app.get("/v1/projects/{project_id}/runs/{run_id}/status")
    def get_project_run_status(
        project_id: str,
        run_id: str,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        with sessions() as session:
            project = session.get(ProjectRow, project_id)
            if project is None:
                raise HTTPException(status_code=404, detail=f"project {project_id!r} was not found")
            run = session.scalar(
                select(WorkflowRunRow).where(
                    WorkflowRunRow.id == run_id, WorkflowRunRow.project_id == project_id
                )
            )
            if run is None:
                raise HTTPException(status_code=404, detail=f"run {run_id!r} was not found")
            tasks = session.scalars(
                select(TaskRow)
                .where(TaskRow.run_id == run_id)
                .order_by(TaskRow.created_at, TaskRow.id)
            ).all()
            submission = session.get(RunSubmissionRow, run_id)
            return {
                "project_id": project_id,
                "run_id": run.id,
                "accession": run.accession,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "submission": (
                    {
                        "state": submission.state,
                        "heartbeat_at": (
                            submission.heartbeat_at.isoformat() if submission.heartbeat_at else None
                        ),
                        "cancel_requested": submission.cancel_requested,
                        "error": submission.error,
                    }
                    if submission is not None
                    else None
                ),
                "tasks": [
                    {
                        "task_id": task.id,
                        "stage_id": task.stage_id,
                        "subject_kind": task.subject_kind,
                        "subject_id": task.subject_id,
                        "state": task.state,
                        "version": task.version,
                        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                    }
                    for task in tasks
                ],
            }

    @app.get("/v1/projects/{project_id}/runs/{run_id}/events")
    def stream_project_run_events(
        project_id: str,
        run_id: str,
        max_seconds: Annotated[float, Query(ge=1, le=3600)] = 300,
        _: None = Depends(authenticate),
    ) -> StreamingResponse:
        with sessions() as session:
            if session.get(ProjectRow, project_id) is None:
                raise HTTPException(status_code=404, detail=f"project {project_id!r} was not found")
            if (
                session.scalar(
                    select(WorkflowRunRow).where(
                        WorkflowRunRow.id == run_id, WorkflowRunRow.project_id == project_id
                    )
                )
                is None
            ):
                raise HTTPException(status_code=404, detail=f"run {run_id!r} was not found")

        def events() -> Iterator[str]:
            deadline = time.monotonic() + max_seconds
            previous: str | None = None
            while True:
                with sessions() as session:
                    run = session.scalar(
                        select(WorkflowRunRow).where(
                            WorkflowRunRow.id == run_id, WorkflowRunRow.project_id == project_id
                        )
                    )
                    if run is None:
                        return
                    tasks = session.scalars(
                        select(TaskRow)
                        .where(TaskRow.run_id == run_id)
                        .order_by(TaskRow.created_at, TaskRow.id)
                    ).all()
                    submission = session.get(RunSubmissionRow, run_id)
                    data = {
                        "project_id": project_id,
                        "run_id": run_id,
                        "status": run.status,
                        "submission": (
                            {
                                "state": submission.state,
                                "heartbeat_at": (
                                    submission.heartbeat_at.isoformat()
                                    if submission.heartbeat_at
                                    else None
                                ),
                                "cancel_requested": submission.cancel_requested,
                                "error": submission.error,
                            }
                            if submission is not None
                            else None
                        ),
                        "tasks": [
                            {
                                "task_id": task.id,
                                "stage_id": task.stage_id,
                                "state": task.state,
                                "version": task.version,
                                "updated_at": (
                                    task.updated_at.isoformat() if task.updated_at else None
                                ),
                            }
                            for task in tasks
                        ],
                    }
                encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
                if encoded != previous:
                    digest = hashlib.sha256(encoded.encode()).hexdigest()[:24]
                    yield f"id: {digest}\nevent: run-status\ndata: {encoded}\n\n"
                    previous = encoded
                if data["status"] in {"succeeded", "failed", "stopped", "cancelled"}:
                    return
                if time.monotonic() >= deadline:
                    yield "event: timeout\ndata: {}\n\n"
                    return
                time.sleep(1.0)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/provenance/attempts/{attempt_id}")
    def get_attempt_lineage(
        attempt_id: str,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            return run_lineage(sessions, attempt_ids=(attempt_id,), root_attempt_id=attempt_id)
        except ProvenanceNodeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/provenance/runs/{run_id}")
    def get_run_lineage(
        run_id: str,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            return run_lineage(sessions, run_id=run_id)
        except ProvenanceNodeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/provenance/projects/{project_id}/version-drift")
    def get_project_version_drift(
        project_id: str,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            graph = project_lineage(sessions, project_id=project_id)
            return version_drift(graph["attempts"])
        except ProvenanceNodeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/provenance/projects/{project_id}")
    def get_project_lineage(
        project_id: str,
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            return project_lineage(sessions, project_id=project_id)
        except ProvenanceNodeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


def _parse_workflow_inputs(
    request: WorkflowRunSubmission,
) -> dict[str, VersionedContract | tuple[VersionedContract, ...]]:
    declarations = {name: item.contract for name, item in request.workflow.inputs.items()}
    if set(request.inputs) != set(declarations):
        raise ValueError(
            "inputs must exactly match workflow declarations; "
            f"expected {sorted(declarations)}, got {sorted(request.inputs)}"
        )
    parsed: dict[str, VersionedContract | tuple[VersionedContract, ...]] = {}
    for name, declaration in declarations.items():
        raw_values = request.inputs[name]
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        if not values:
            raise ValueError(f"input {name!r} cannot be an empty list")
        contracts: list[VersionedContract] = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError(f"input {name!r} must be a contract object")
            try:
                contract = load_contract(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid input {name!r}: {exc}") from exc
            if contract.schema_id() != declaration:
                raise ValueError(
                    f"input {name!r} requires {declaration}, got {contract.schema_id()}"
                )
            contracts.append(contract)
        parsed[name] = tuple(contracts) if isinstance(raw_values, list) else contracts[0]
    return parsed


def _artifact_refs(value: object) -> tuple[ArtifactRef, ...]:
    """Find typed artifact references nested in normalized contract input values."""
    from pydantic import BaseModel

    if isinstance(value, ArtifactRef):
        return (value,)
    if isinstance(value, BaseModel):
        return tuple(
            reference
            for field_name in type(value).model_fields
            for reference in _artifact_refs(getattr(value, field_name))
        )
    if isinstance(value, dict):
        return tuple(reference for child in value.values() for reference in _artifact_refs(child))
    if isinstance(value, (tuple, list)):
        return tuple(reference for child in value for reference in _artifact_refs(child))
    return ()
