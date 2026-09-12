"""add hardware_station to measurements and attachments

Revision ID: 8b9651c496c5
Revises: fb5f1fc21ed6
Create Date: 2026-09-12 13:52:35.092347

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b9651c496c5'
down_revision: Union[str, None] = 'fb5f1fc21ed6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('attachments', sa.Column('hardware_station', sa.String(length=16), nullable=True))
    op.add_column('measurements', sa.Column('hardware_station', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('measurements', 'hardware_station')
    op.drop_column('attachments', 'hardware_station')
