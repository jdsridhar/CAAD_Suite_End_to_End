"""Authenticated read-only HTTP endpoints for workflow provenance."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.migrate import upgrade
from caddsuite.storage.paths import database_path, resolve_data_root
from caddsuite.storage.provenance_graph import (
    ProvenanceNodeNotFound,
    project_lineage,
    run_lineage,
)


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
