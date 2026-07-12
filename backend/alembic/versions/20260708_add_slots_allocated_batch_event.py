"""Add SLOTS_ALLOCATED to batcheventtype enum

Revision ID: c8d9e0f1a2b3
Revises: d7cdeadbb810
Create Date: 2026-07-08
"""
from alembic import op

revision: str = 'c8d9e0f1a2b3'
down_revision: str = 'd7cdeadbb810'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL allows adding new values to an existing ENUM type.
    # IF NOT EXISTS prevents errors on repeated runs.
    op.execute("ALTER TYPE batcheventtype ADD VALUE IF NOT EXISTS 'SLOTS_ALLOCATED'")


def downgrade() -> None:
    # PostgreSQL does not support removing ENUM values without recreating the type.
    # Downgrade is intentionally a no-op — the value is harmless if unused.
    pass
