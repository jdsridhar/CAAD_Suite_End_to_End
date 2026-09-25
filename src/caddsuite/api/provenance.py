"""Authenticated read-only HTTP endpoints for workflow provenance."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import JsonValue
from sqlalchemy import select

from caddsuite.application.handlers import StageHandlerDiscoveryError, StageHandlerRegistry
from caddsuite.application.runtime import LocalWorkflowRuntime
from caddsuite.application.version_drift import version_drift
from caddsuite.contracts.base import ArtifactRef, ContractModel, VersionedContract, load_contract
from caddsuite.domain.identity import ULIDStr
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import ArtifactRow, ProjectRow, TaskRow, WorkflowRunRow
from caddsuite.storage.paths import artifacts_root, database_path, resolve_data_root
from caddsuite.storage.provenance_graph import (
    ProvenanceNodeNotFound,
    project_lineage,
    run_lineage,
)
from caddsuite.workflow.compiler import WorkflowCompileError
from caddsuite.workflow.definition import WorkflowDefinition

logger = logging.getLogger(__name__)


class WorkflowRunSubmission(ContractModel):
    """Normalized workflow definition and contract JSON for a local API run."""

    workflow: WorkflowDefinition
    inputs: dict[str, JsonValue]


def create_app(
    *,
    data_root: Path | None = None,
    token: str,
    allowed_origins: tuple[str, ...] = (),
) -> FastAPI:
    """Build a provenance API; callers must provide a per-install bearer token."""
    if not token or not token.strip():
        raise ValueError("API bearer token must be configured")
    root = resolve_data_root(data_root)
    upgrade(database_path(root))
    engine = create_db_engine(database_path(root))
    sessions = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="CADD Suite API", version="0.1.0", lifespan=lifespan)
    app.state.sessions = sessions
    app.state.allowed_origins = frozenset(allowed_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authenticate(
        authorization: Annotated[str | None, Header()] = None,
        origin: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        origins: frozenset[str] = app.state.allowed_origins
        if origin is not None and origin not in origins:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")

    @app.post("/v1/projects/{project_id}/runs/{run_id}/execute")
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
            registry = StageHandlerRegistry.discover()
            compiled = registry.compile(request.workflow)
        except StageHandlerDiscoveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        declarations = {name: item.contract for name, item in request.workflow.inputs.items()}
        if set(request.inputs) != set(declarations):
            raise HTTPException(
                status_code=422,
                detail=(
                    "inputs must exactly match workflow declarations; "
                    f"expected {sorted(declarations)}, got {sorted(request.inputs)}"
                ),
            )
        parsed: dict[str, VersionedContract | tuple[VersionedContract, ...]] = {}
        artifact_store = ArtifactStore(artifacts_root(root))
        for name, declaration in declarations.items():
            raw_values = request.inputs[name]
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            if not values:
                raise HTTPException(
                    status_code=422, detail=f"input {name!r} cannot be an empty list"
                )
            contracts = []
            for value in values:
                if not isinstance(value, dict):
                    raise HTTPException(
                        status_code=422, detail=f"input {name!r} must be a contract object"
                    )
                try:
                    contract = load_contract(value)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(
                        status_code=422, detail=f"invalid input {name!r}: {exc}"
                    ) from exc
                if contract.schema_id() != declaration:
                    raise HTTPException(
                        status_code=422,
                        detail=f"input {name!r} requires {declaration}, got {contract.schema_id()}",
                    )
                contracts.append(contract)
            parsed[name] = tuple(contracts) if isinstance(raw_values, list) else contracts[0]
        run_created = False
        try:
            with sessions() as session:
                if session.get(ProjectRow, project_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"project {project_id!r} was not found"
                    )
                if session.get(WorkflowRunRow, stable_run_id) is not None:
                    raise HTTPException(
                        status_code=409, detail=f"run {stable_run_id!r} already exists"
                    )
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
                            detail=(
                                f"input artifact {reference.artifact_id!r} failed hash verification"
                            ),
                        )

            workflow_payload = request.workflow.model_dump(mode="json", by_alias=True)
            input_payload = request.model_dump(mode="json")["inputs"]
            workflow_hash = hashlib.sha256(
                json.dumps(workflow_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            config_hash = hashlib.sha256(
                json.dumps(input_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            with LocalWorkflowRuntime.open(
                data_root=root,
                handlers=lambda services: registry.build_handlers(request.workflow, services),
            ) as runtime:
                with runtime.sessions.begin() as session:
                    run = WorkflowRunRow(
                        id=stable_run_id,
                        project_id=project_id,
                        accession="RUN-" + stable_run_id,
                        workflow_hash=workflow_hash,
                        config_hash=config_hash,
                        status="running",
                        started_at=datetime.now(UTC),
                    )
                    session.add(run)
                run_created = True
                outcome = runtime.run(compiled, run_id=stable_run_id, inputs=parsed)
                run_status = (
                    "failed" if outcome.failures else "stopped" if outcome.stopped else "succeeded"
                )
                with runtime.sessions.begin() as session:
                    stored_run = session.get(WorkflowRunRow, stable_run_id)
                    if stored_run is not None:
                        stored_run.status = run_status
                        stored_run.finished_at = datetime.now(UTC)
                return {
                    "project_id": project_id,
                    "run_id": stable_run_id,
                    "status": run_status,
                    "tasks": [
                        {
                            "task_id": task.task_id,
                            "stage_id": task.stage_id,
                            "subject_id": task.subject_id,
                            "state": task.state.value,
                            "cache_hit": task.cache_hit,
                            "error": task.error,
                        }
                        for task in outcome.tasks
                    ],
                }
        except HTTPException:
            raise
        except Exception as exc:
            if run_created:
                try:
                    with sessions.begin() as session:
                        failed_run = session.get(WorkflowRunRow, stable_run_id)
                        if failed_run is not None and failed_run.status == "running":
                            failed_run.status = "failed"
                            failed_run.finished_at = datetime.now(UTC)
                except Exception:
                    logger.exception(
                        "could not persist failed state for API workflow run %s", stable_run_id
                    )
            raise HTTPException(
                status_code=500,
                detail="workflow execution failed during runtime initialization or supervision",
            ) from exc

    @app.get("/v1/workflows/capabilities")
    def get_workflow_capabilities(
        _: None = Depends(authenticate),
    ) -> dict[str, object]:
        try:
            snapshot = StageHandlerRegistry.discover().snapshot()
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
            registry = StageHandlerRegistry.discover()
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
            return {
                "project_id": project_id,
                "run_id": run.id,
                "accession": run.accession,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
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
