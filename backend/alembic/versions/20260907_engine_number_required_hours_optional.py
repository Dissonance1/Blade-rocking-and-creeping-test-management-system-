"""Make work_orders.engine_number required, engine_hours optional

Operators asked for Engine Number to be mandatory on the Start Blade Entry
form (it's how repeat visits of the same engine are told apart) while
Engine Hours is frequently not on hand at intake time.

Revision ID: 8d5e6f7a9b1c
Revises: 7c4d5e6f7a8b
Create Date: 2026-09-07
"""
import sqlalchemy as sa
from alembic import op

revision: str = '8d5e6f7a9b1c'
down_revision: str = '7c4d5e6f7a8b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE work_orders SET engine_number = 'UNKNOWN' WHERE engine_number IS NULL"
    )
    op.alter_column("work_orders", "engine_number", nullable=False)
    op.alter_column("work_orders", "engine_hours", nullable=True)


def downgrade() -> None:
    op.alter_column("work_orders", "engine_hours", nullable=False)
    op.alter_column("work_orders", "engine_number", nullable=True)
