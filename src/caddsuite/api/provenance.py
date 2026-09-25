"""Authenticated read-only HTTP endpoints for workflow provenance."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import select

from caddsuite.application.handlers import StageHandlerDiscoveryError, StageHandlerRegistry
from caddsuite.application.version_drift import version_drift
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.models import ProjectRow, TaskRow, WorkflowRunRow
from caddsuite.storage.paths import database_path, resolve_data_root
from caddsuite.storage.provenance_graph import (
    ProvenanceNodeNotFound,
    project_lineage,
    run_lineage,
)
from caddsuite.workflow.compiler import WorkflowCompileError
from caddsuite.workflow.definition import WorkflowDefinition


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
