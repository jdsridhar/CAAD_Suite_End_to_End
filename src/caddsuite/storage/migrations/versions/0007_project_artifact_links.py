"""Link uploaded artifacts to their owning projects.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_artifacts",
        sa.Column("project_id", sa.String(length=26), nullable=False),
        sa.Column("artifact_id", sa.String(length=26), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("project_id", "artifact_id", "role"),
    )


def downgrade() -> None:
    op.drop_table("project_artifacts")
