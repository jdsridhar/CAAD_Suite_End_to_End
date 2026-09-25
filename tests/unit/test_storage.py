"""Database: migrations, pragmas, integrity, accessions, artifact registration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from caddsuite.domain.identity import AccessionKind
from caddsuite.storage import migrate
from caddsuite.storage.accessions import (
    allocate,
    next_compound_accession,
    next_derived_accession,
    next_run_accession,
)
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.db import create_db_engine, make_session_factory
from caddsuite.storage.models import ArtifactRow, CompoundRow, ProjectRow


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "caddsuite.db"
    migrate.upgrade(path)
    return path


@pytest.fixture
def session(db_path: Path) -> Iterator[Session]:
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with factory() as s:
        yield s
    engine.dispose()


def _project(session: Session, slug: str = "pparg-demo") -> ProjectRow:
    project = ProjectRow(slug=slug, name=slug)
    session.add(project)
    session.flush()
    return project


def test_upgrade_reaches_head(db_path: Path) -> None:
    assert migrate.current_revision(db_path) == "0007"


def test_models_match_migrations(db_path: Path) -> None:
    migrate.check(db_path)  # raises if models changed without a migration


def test_sqlite_pragmas_are_applied(session: Session) -> None:
    assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    assert session.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"


def test_foreign_keys_are_enforced(session: Session) -> None:
    session.add(
        CompoundRow(
            project_id="01J8ZZZZZZZZZZZZZZZZZZZZZZ",
            accession="CMP0001",
            name="orphan",
            inchikey="BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            payload={},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_timestamps_are_utc_aware_and_naive_input_is_rejected(session: Session) -> None:
    project = _project(session)
    session.commit()
    loaded = session.scalar(select(ProjectRow).where(ProjectRow.id == project.id))
    assert loaded is not None
    assert loaded.created_at.tzinfo is not None
    session.add(ProjectRow(slug="naive", name="naive", created_at=datetime(2026, 9, 23)))
    with pytest.raises(StatementError, match="naive datetime"):
        session.flush()


def test_accessions_are_sequential_and_scoped(session: Session) -> None:
    p1, p2 = _project(session, "p1"), _project(session, "p2")
    assert next_compound_accession(session, p1.id) == "CMP0001"
    assert next_compound_accession(session, p1.id) == "CMP0002"
    assert next_compound_accession(session, p2.id) == "CMP0001"  # independent per project
    assert (
        next_derived_accession(session, p1.id, "CMP0001", AccessionKind.DOCKING)
        == "CMP0001_DOCK_001"
    )
    assert (
        next_derived_accession(session, p1.id, "CMP0001", AccessionKind.DOCKING)
        == "CMP0001_DOCK_002"
    )
    assert (
        next_derived_accession(session, p1.id, "CMP0002", AccessionKind.DOCKING)
        == "CMP0002_DOCK_001"
    )
    assert (
        next_derived_accession(session, p1.id, "CMP0001", AccessionKind.POSE) == "CMP0001_POSE_001"
    )
    assert next_run_accession(session, p1.id, date(2026, 9, 23)) == "RUN-20260923-001"
    assert next_run_accession(session, p1.id, date(2026, 9, 24)) == "RUN-20260924-001"
    assert allocate(session, p1.id, AccessionKind.TARGET) == 1


def test_register_blob_is_idempotent(session: Session, tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    blob = store.put_bytes(b"HETATM    1  C1  LIG X 999 ...")
    row1 = register_blob(
        session,
        blob,
        kind="structure.pdb",
        media_type="chemical/x-pdb",
        original_name="RC34__5NIU_complex.pdb",
    )
    row2 = register_blob(
        session,
        store.put_bytes(b"HETATM    1  C1  LIG X 999 ..."),
        kind="structure.pdb",
        media_type="chemical/x-pdb",
    )
    assert row1.id == row2.id
    assert session.scalar(select(ArtifactRow.original_name)) == "RC34__5NIU_complex.pdb"
    assert row1.created_at <= datetime.now(UTC)
