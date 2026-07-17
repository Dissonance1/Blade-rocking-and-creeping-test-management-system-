"""Add CREATED, MEASUREMENTS_RECORDED, SET_MAKING, BALANCED to batcheventtype enum

Revision ID: e1f2a3b4c5d6
Revises: 7ab6f684a83c
Create Date: 2026-07-17
"""
from alembic import op

revision: str = '9f4c2e7a1d08'
down_revision: str = '7ab6f684a83c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL allows adding new values to an existing ENUM type.
    # IF NOT EXISTS prevents errors on repeated runs.
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'CREATED'")
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'MEASUREMENTS_RECORDED'")
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'SET_MAKING'")
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'BALANCED'")


def downgrade() -> None:
    # PostgreSQL does not support removing ENUM values without recreating the type.
    # Downgrade is intentionally a no-op — the value is harmless if unused.
    pass
