"""add ocr detection fields to attachments

Revision ID: 7ab6f684a83c
Revises: f9e8d7c6b5a4
Create Date: 2026-07-16 17:50:52.519136

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ab6f684a83c'
down_revision: Union[str, None] = 'f9e8d7c6b5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('attachments', sa.Column('ocr_field_name', sa.String(length=32), nullable=True))
    op.add_column('attachments', sa.Column('ocr_detected_text', sa.String(length=64), nullable=True))
    op.add_column('attachments', sa.Column('ocr_confidence', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('attachments', 'ocr_confidence')
    op.drop_column('attachments', 'ocr_detected_text')
    op.drop_column('attachments', 'ocr_field_name')
