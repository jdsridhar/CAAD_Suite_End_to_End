from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from caddsuite.cli.input_loader import load_workflow_inputs
from caddsuite.contracts.base import ArtifactRef
from caddsuite.contracts.registry import Conformer
from caddsuite.domain.identity import new_ulid
from caddsuite.storage import migrate
from caddsuite.storage.artifacts import ArtifactStore
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ArtifactRow


def _fixture(tmp_path: Path):
    data_root = tmp_path / "data"
    db_path = data_root / "caddsuite.sqlite3"
    migrate.upgrade(db_path)
    engine = create_db_engine(db_path)
    sessions = make_session_factory(engine)
    store = ArtifactStore(data_root / "artifacts")
    return engine, sessions, store


def test_input_loader_registers_hash_linked_contract_artifacts(tmp_path: Path) -> None:
    geometry = tmp_path / "conformer.sdf"
    geometry.write_text("fixture SDF bytes\n", encoding="utf-8")
    artifact_id = new_ulid()
    conformer = Conformer(
        id=new_ulid(),
        form_id=new_ulid(),
        compound_id=new_ulid(),
        generator="manual_fixture",
        structure=ArtifactRef(artifact_id=artifact_id, role="conformer_structure"),
    )
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {"geometry": conformer.model_dump(mode="json")},
                "artifacts": {artifact_id: geometry.name},
            }
        ),
        encoding="utf-8",
    )
    engine, sessions, store = _fixture(tmp_path)
    try:
        loaded = load_workflow_inputs(
            manifest,
            declarations={"geometry": "conformer/1.1"},
            sessions=sessions,
            artifacts=store,
        )
        result = loaded["geometry"]
        assert isinstance(result, Conformer)
        assert result.structure.sha256 is not None
        assert store.verify(result.structure.sha256)
        with sessions() as session:
            row = session.scalar(
                select(ArtifactRow).where(ArtifactRow.id == result.structure.artifact_id)
            )
        assert row is not None
    finally:
        engine.dispose()


def test_input_loader_rejects_artifact_hash_mismatch(tmp_path: Path) -> None:
    geometry = tmp_path / "conformer.sdf"
    geometry.write_text("actual bytes\n", encoding="utf-8")
    artifact_id = new_ulid()
    conformer = Conformer(
        id=new_ulid(),
        form_id=new_ulid(),
        compound_id=new_ulid(),
        generator="manual_fixture",
        structure=ArtifactRef(artifact_id=artifact_id, role="conformer_structure", sha256="0" * 64),
    )
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {"geometry": conformer.model_dump(mode="json")},
                "artifacts": {artifact_id: geometry.name},
            }
        ),
        encoding="utf-8",
    )
    engine, sessions, store = _fixture(tmp_path)
    try:
        with pytest.raises(ValueError, match="SHA-256"):
            load_workflow_inputs(
                manifest,
                declarations={"geometry": "conformer/1.1"},
                sessions=sessions,
                artifacts=store,
            )
    finally:
        engine.dispose()
