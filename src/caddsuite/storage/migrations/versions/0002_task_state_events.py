"""Append-only task state transition history.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "task_state_events",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("task_id", sa.String(length=26), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version"),
    )


def downgrade() -> None:
    op.drop_table("task_state_events")
    op.drop_column("tasks", "version")
