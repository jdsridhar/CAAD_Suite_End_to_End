from __future__ import annotations

import hashlib
from pathlib import Path

from caddsuite.application.run_sources import capture_cli_run_sources
from caddsuite.domain.identity import new_ulid
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ArtifactRow, ProjectArtifactRow, ProjectRow
from caddsuite.storage.paths import artifacts_root, database_path


def test_cli_sources_are_persisted_as_run_scoped_project_artifacts(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    migrate.upgrade(database_path(data_root))
    engine = create_db_engine(database_path(data_root))
    sessions = make_session_factory(engine)
    store = ArtifactStore(artifacts_root(data_root))
    workflow = tmp_path / "workflow.yaml"
    inputs = tmp_path / "inputs.json"
    workflow_bytes = b"schema: caddsuite.workflow/1\nname: repro\nstages: []\n"
    input_bytes = b'{"inputs":{}}\n'
    workflow.write_bytes(workflow_bytes)
    inputs.write_bytes(input_bytes)
    project_id = new_ulid()
    run_id = new_ulid()

    try:
        with sessions.begin() as session:
            session.add(ProjectRow(id=project_id, slug="repro-test", name="Repro test"))
            session.flush()
            capture_cli_run_sources(
                session,
                artifact_store=store,
                project_id=project_id,
                run_id=run_id,
                workflow_file=workflow,
                inputs_file=inputs,
                workflow_bytes=workflow_bytes,
                input_bytes=input_bytes,
            )

        with sessions() as session:
            links = session.query(ProjectArtifactRow).filter_by(project_id=project_id).all()
            assert {link.role for link in links} == {
                f"run_{run_id}_workflow",
                f"run_{run_id}_inputs",
            }
            artifacts = {row.kind: row for row in session.query(ArtifactRow).all()}
            workflow_hash = hashlib.sha256(workflow_bytes).hexdigest()
            input_hash = hashlib.sha256(input_bytes).hexdigest()
            assert artifacts["workflow_source"].sha256 == workflow_hash
            assert artifacts["input_manifest"].sha256 == input_hash
            assert store.verify(workflow_hash)
            assert store.verify(input_hash)
            assert store.path_for(workflow_hash).read_bytes() == workflow_bytes
            assert store.path_for(input_hash).read_bytes() == input_bytes
    finally:
        engine.dispose()
