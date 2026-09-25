"""Persist the versioned task-attempt contract and its captured environment.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("task_attempts") as batch_op:
        batch_op.add_column(sa.Column("environment_id", sa.String(length=26), nullable=True))
        batch_op.add_column(sa.Column("payload", sa.JSON(), nullable=True))
        batch_op.create_index(
            "ix_task_attempts_environment_id", ["environment_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("task_attempts") as batch_op:
        batch_op.drop_index("ix_task_attempts_environment_id")
        batch_op.drop_column("payload")
        batch_op.drop_column("environment_id")
