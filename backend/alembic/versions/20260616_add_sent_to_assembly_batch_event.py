"""Add SENT_TO_ASSEMBLY to batcheventtype enum

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-16
"""
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: str = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL allows adding new values to an existing ENUM type.
    # IF NOT EXISTS prevents errors on repeated runs.
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'SENT_TO_ASSEMBLY'")


def downgrade() -> None:
    # PostgreSQL does not support removing ENUM values without recreating the type.
    # Downgrade is intentionally a no-op — the value is harmless if unused.
    pass
