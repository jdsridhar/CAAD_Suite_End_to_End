"""Allocation of human-readable accessions (CMP0001, CMP0001_DOCK_001, RUN-20260923-001).

Allocation is a single atomic SQL upsert (``INSERT … ON CONFLICT DO UPDATE … RETURNING``),
so two concurrent writers can never receive the same number. The SQLite dialect is used
here; a PostgreSQL deployment would use the equivalent PostgreSQL upsert (ADR-0005).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from caddsuite.domain.identity import (
    AccessionKind,
    compound_accession,
    derived_accession,
    run_accession,
    target_accession,
)
from caddsuite.storage.models import AccessionCounterRow


def allocate(session: Session, project_id: str, kind: AccessionKind, scope: str = "") -> int:
    """Return the next sequence number for ``(project, kind, scope)``, starting at 1."""
    stmt = (
        sqlite_insert(AccessionCounterRow)
        .values(project_id=project_id, kind=kind.value, scope=scope, last_value=1)
        .on_conflict_do_update(
            index_elements=["project_id", "kind", "scope"],
            set_={"last_value": AccessionCounterRow.last_value + 1},
        )
        .returning(AccessionCounterRow.last_value)
    )
    return int(session.execute(stmt).scalar_one())


def next_compound_accession(session: Session, project_id: str) -> str:
    return compound_accession(allocate(session, project_id, AccessionKind.COMPOUND))


def next_target_accession(session: Session, project_id: str) -> str:
    return target_accession(allocate(session, project_id, AccessionKind.TARGET))


def next_derived_accession(
    session: Session, project_id: str, compound: str, kind: AccessionKind
) -> str:
    """e.g. ``CMP0001_DOCK_002``. The sequence is scoped per compound and kind."""
    number = allocate(session, project_id, kind, scope=compound)
    return derived_accession(compound, kind, number)


def next_run_accession(session: Session, project_id: str, run_date: date) -> str:
    number = allocate(session, project_id, AccessionKind.RUN, scope=run_date.isoformat())
    return run_accession(run_date, number)
