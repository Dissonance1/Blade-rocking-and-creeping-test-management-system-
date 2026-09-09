"""Add raw_weight_kg to measurements

Stores the weighing machine's own raw reading (kg) alongside the derived
weight_grams/static_moment_gcm, instead of only back-computing it for
display (weight_grams / WEIGHT_TO_GRAMS_FACTOR) — the actual source value
is available at write time, so it's captured directly rather than
reconstructed with rounding loss later.

Revision ID: fb5f1fc21ed6
Revises: 8d5e6f7a9b1c
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision: str = 'fb5f1fc21ed6'
down_revision: str = '8d5e6f7a9b1c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "measurements",
        sa.Column("raw_weight_kg", sa.Numeric(12, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("measurements", "raw_weight_kg")
