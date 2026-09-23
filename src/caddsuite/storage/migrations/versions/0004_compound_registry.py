"""Index standardized compound identities and retain all raw input records.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_compounds_project_inchikey", table_name="compounds")
    op.create_index(
        "uq_compounds_project_inchikey",
        "compounds",
        ["project_id", "inchikey"],
        unique=True,
    )
    op.create_table(
        "compound_inputs",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("compound_id", sa.String(length=26), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["compound_id"], ["compounds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_compound_inputs_compound_id",
        "compound_inputs",
        ["compound_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_compound_inputs_compound_id", table_name="compound_inputs")
    op.drop_table("compound_inputs")
    op.drop_index("uq_compounds_project_inchikey", table_name="compounds")
    op.create_index(
        "ix_compounds_project_inchikey",
        "compounds",
        ["project_id", "inchikey"],
        unique=False,
    )
