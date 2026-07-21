"""drop_rejection_reasons — remove the unused OH-side reject-with-reason feature

The OH-side `POST /blades/{id}/reject` endpoint (which required a
`rejection_reason_id` FK into `rejection_reasons`) was dead code — no
frontend UI ever called it. The live reject flow is the Assembly-side
`POST /assembly/blades/{id}/reject`, which takes free-text notes and has
no relationship to this table. Dropping `rejection_reasons`, the
`blades.rejection_reason_id` FK column, and the now-orphaned
`blades.rejection_notes` column.

Revision ID: 8a1b2c3d4e5f
Revises: 7f8e9d0c1b2a
Create Date: 2026-07-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8a1b2c3d4e5f'
down_revision: Union[str, None] = '7f8e9d0c1b2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    blade_columns = {c["name"] for c in inspector.get_columns("blades")}
    if "rejection_reason_id" in blade_columns:
        fk_names = [
            fk["name"] for fk in inspector.get_foreign_keys("blades")
            if fk.get("referred_table") == "rejection_reasons"
        ]
        for fk_name in fk_names:
            op.drop_constraint(fk_name, "blades", type_="foreignkey")
        op.drop_column("blades", "rejection_reason_id")
    if "rejection_notes" in blade_columns:
        op.drop_column("blades", "rejection_notes")

    if "rejection_reasons" in inspector.get_table_names():
        op.drop_table("rejection_reasons")


def downgrade() -> None:
    op.create_table(
        "rejection_reasons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        op.f("ix_rejection_reasons_code"), "rejection_reasons", ["code"], unique=True
    )

    op.add_column("blades", sa.Column("rejection_notes", sa.Text(), nullable=True))
    op.add_column(
        "blades",
        sa.Column("rejection_reason_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "blades_rejection_reason_id_fkey",
        "blades",
        "rejection_reasons",
        ["rejection_reason_id"],
        ["id"],
        ondelete="SET NULL",
    )
