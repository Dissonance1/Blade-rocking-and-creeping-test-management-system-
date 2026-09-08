"""Add ocr_reverify_state for the weekly OCR retraining pipeline

Tracks, per OCR-scan attachment, how many consecutive weekly re-checks the
currently-deployed model has gotten right in a row — lets the retraining
pipeline skip images that have already proven stable instead of re-running
inference against the whole ever-growing corpus every week (see
backend/finetune/reverify_dataset.py).

Revision ID: 9e1f2a3b4c5d
Revises: 8d5e6f7a9b1c
Create Date: 2026-09-08
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '9e1f2a3b4c5d'
down_revision: str = '8d5e6f7a9b1c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_reverify_state",
        sa.Column(
            "attachment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("consecutive_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result_matched", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("ocr_reverify_state")
