"""Add RETURNED_TO_OH, ACCEPTED_BY_OH to batcheventtype enum

Revision ID: 9b2c3d4e5f6a
Revises: 8a1b2c3d4e5f
Create Date: 2026-07-22
"""
from alembic import op

revision: str = '9b2c3d4e5f6a'
down_revision: str = '8a1b2c3d4e5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL allows adding new values to an existing ENUM type.
    # IF NOT EXISTS prevents errors on repeated runs.
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'RETURNED_TO_OH'")
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'ACCEPTED_BY_OH'")


def downgrade() -> None:
    # PostgreSQL does not support removing ENUM values without recreating the type.
    # Downgrade is intentionally a no-op — the value is harmless if unused.
    pass
