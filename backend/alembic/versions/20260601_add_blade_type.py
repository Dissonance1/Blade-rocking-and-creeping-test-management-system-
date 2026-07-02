"""add_blade_type_column

Revision ID: a1b2c3d4e5f6
Revises: 73aae12be49a
Create Date: 2026-06-01 09:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '73aae12be49a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use ADD COLUMN IF NOT EXISTS so this is safe to run on DBs where the
    # initial schema already included blade_type.
    op.execute("ALTER TABLE blades ADD COLUMN IF NOT EXISTS blade_type bladetype NOT NULL DEFAULT 'LPTR'")


def downgrade() -> None:
    op.drop_column('blades', 'blade_type')
