"""Scope blade serial_number uniqueness to (batch_number, blade_type)

Serial numbers are now auto-assigned per batch per blade type (1..90 for
LPTR, 1..90 for HPTR, independently) instead of being globally unique and
manually entered — so the same serial legitimately recurs across different
batches/types.

Revision ID: e1f2a3b4c5d6
Revises: c8d9e0f1a2b3
Create Date: 2026-07-12
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: str = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_blades_serial_number", table_name="blades")
    op.create_index("ix_blades_serial_number", "blades", ["serial_number"], unique=False)
    op.create_unique_constraint(
        "uq_blade_batch_type_serial",
        "blades",
        ["batch_number", "blade_type", "serial_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_blade_batch_type_serial", "blades", type_="unique")
    op.drop_index("ix_blades_serial_number", table_name="blades")
    op.create_index("ix_blades_serial_number", "blades", ["serial_number"], unique=True)
