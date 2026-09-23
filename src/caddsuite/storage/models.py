"""ORM models for the metadata database (SQLAlchemy 2.0, typed).

What goes where (ADR-0005)
--------------------------
* **Rows**: identities, relationships, states, hashes, small scalars.
* **``payload`` JSON columns**: the full normalized contract (``schema_version`` included),
  so the database stays schema-stable while contracts evolve through upcasters.
* **Never in the DB**: trajectories, structures, logs. Those are content-addressed
  artifacts on disk, referenced by sha256 (``artifacts`` table).

Provenance edges follow W3C PROV: a task *attempt* is an activity. It *used* and
*generated* artifacts (``attempt_artifacts``) and was carried out with software
agents (``attempt_agents``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column

from caddsuite.domain.identity import new_ulid


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend.

    SQLite has no timezone support and returns naive values. We refuse naive input and
    re-attach UTC on output, so provenance timestamps are never ambiguous.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; use timezone-aware UTC datetimes")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def _ulid_pk() -> MappedColumn[str]:
    return mapped_column(String(26), primary_key=True, default=new_ulid)


def _created() -> MappedColumn[datetime]:
    return mapped_column(UtcDateTime(), default=utcnow, nullable=False)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


# --------------------------------------------------------------------------- registry
class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = _ulid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class AccessionCounterRow(Base):
    """Per-project sequence for human-readable accessions (CMP0001, CMP0001_DOCK_001, …)."""

    __tablename__ = "accession_counters"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    last_value: Mapped[int] = mapped_column(Integer)


class CompoundRow(Base):
    __tablename__ = "compounds"
    __table_args__ = (
        UniqueConstraint("project_id", "accession"),
        Index("uq_compounds_project_inchikey", "project_id", "inchikey", unique=True),
    )

    id: Mapped[str] = _ulid_pk()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    accession: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    inchikey: Mapped[str] = mapped_column(String(27))
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _created()


class CompoundInputRow(Base):
    """Every raw user submission linked to its standardized chemical identity."""

    __tablename__ = "compound_inputs"
    __table_args__ = (Index("ix_compound_inputs_compound_id", "compound_id"),)

    id: Mapped[str] = _ulid_pk()
    compound_id: Mapped[str] = mapped_column(ForeignKey("compounds.id"))
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _created()


class CompoundFormRow(Base):
    __tablename__ = "compound_forms"

    id: Mapped[str] = _ulid_pk()
    compound_id: Mapped[str] = mapped_column(ForeignKey("compounds.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    smiles: Mapped[str] = mapped_column(Text)
    formal_charge: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------------- orchestration
class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (UniqueConstraint("project_id", "accession"),)

    id: Mapped[str] = _ulid_pk()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    accession: Mapped[str] = mapped_column(String(32))
    workflow_hash: Mapped[str] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_run_stage", "run_id", "stage_id"),)

    id: Mapped[str] = _ulid_pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"))
    stage_id: Mapped[str] = mapped_column(String(64))
    subject_kind: Mapped[str | None] = mapped_column(String(32))
    subject_id: Mapped[str | None] = mapped_column(String(26))
    cache_key: Mapped[str | None] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, onupdate=utcnow)


class TaskStateEventRow(Base):
    """Append-only audit record for every task-state transition."""

    __tablename__ = "task_state_events"
    __table_args__ = (UniqueConstraint("task_id", "version"),)

    id: Mapped[str] = _ulid_pk()
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    version: Mapped[int] = mapped_column(Integer)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class TaskAttemptRow(Base):
    """One execution attempt of a task: a PROV *activity*."""

    __tablename__ = "task_attempts"
    __table_args__ = (UniqueConstraint("task_id", "attempt_no"),)

    id: Mapped[str] = _ulid_pk()
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    executor: Mapped[str] = mapped_column(String(32))
    host: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resources: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    steps: Mapped[list[Any] | None] = mapped_column(JSON)
    platform: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    exit_status: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class TaskCacheRow(Base):
    # Durable normalized output keyed by the complete cache digest.

    __tablename__ = "task_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]]
    source_task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = _created()


# -------------------------------------------------------------------------- artifacts
class ArtifactRow(Base):
    """A content-addressed file. Identity is the sha256 of its bytes."""

    __tablename__ = "artifacts"

    id: Mapped[str] = _ulid_pk()
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(64))
    original_name: Mapped[str | None] = mapped_column(String(255))
    producer_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("task_attempts.id"))
    created_at: Mapped[datetime] = _created()


class AttemptArtifactRow(Base):
    """PROV ``used`` / ``generated`` edges between an attempt and artifacts."""

    __tablename__ = "attempt_artifacts"

    attempt_id: Mapped[str] = mapped_column(ForeignKey("task_attempts.id"), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    direction: Mapped[str] = mapped_column(String(16), primary_key=True)  # used | generated
    role: Mapped[str] = mapped_column(String(64), primary_key=True)


class SoftwareAgentRow(Base):
    __tablename__ = "software_agents"
    __table_args__ = (UniqueConstraint("name", "version", "kind"),)

    id: Mapped[str] = _ulid_pk()
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32))
    license_class: Mapped[str] = mapped_column(String(64))


class AttemptAgentRow(Base):
    __tablename__ = "attempt_agents"

    attempt_id: Mapped[str] = mapped_column(ForeignKey("task_attempts.id"), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("software_agents.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)


class SoftwareEnvironmentRow(Base):
    __tablename__ = "software_environments"
    __table_args__ = (UniqueConstraint("prefix", "lock_sha256"),)

    id: Mapped[str] = _ulid_pk()
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(Text)
    lock_sha256: Mapped[str] = mapped_column(String(64), index=True)
    lock_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"))
    key_packages: Mapped[dict[str, Any]]
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime())


# ---------------------------------------------------------------------------- results
class ResultRow(Base):
    """A normalized contract payload plus promoted scalar(s) for fast dashboards."""

    __tablename__ = "results"
    __table_args__ = (
        Index("ix_results_project_contract", "project_id", "contract"),
        Index("ix_results_subject", "subject_id"),
    )

    id: Mapped[str] = _ulid_pk()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    contract: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    subject_kind: Mapped[str | None] = mapped_column(String(32))
    subject_id: Mapped[str | None] = mapped_column(String(26))
    accession: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]]
    primary_value: Mapped[float | None] = mapped_column(Float)
    primary_unit: Mapped[str | None] = mapped_column(String(32))
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("task_attempts.id"))
    created_at: Mapped[datetime] = _created()


class ValidationIssueRow(Base):
    __tablename__ = "validation_issues"

    id: Mapped[str] = _ulid_pk()
    code: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(32))
    subject_kind: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]]
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = _created()


class DecisionRow(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = _ulid_pk()
    issue_id: Mapped[str | None] = mapped_column(ForeignKey("validation_issues.id"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    chosen_key: Mapped[str] = mapped_column(String(64))
    decided_by: Mapped[str] = mapped_column(String(100))
    decided_at: Mapped[datetime] = mapped_column(UtcDateTime())
    scope: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]]
