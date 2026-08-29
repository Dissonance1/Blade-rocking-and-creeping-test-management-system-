"""Add is_rocking_creep_complete to work_orders

Revision ID: 7c4d5e6f7a8b
Revises: 9b2c3d4e5f6a
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '7c4d5e6f7a8b'
down_revision: str = '9b2c3d4e5f6a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("is_rocking_creep_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "work_orders",
        sa.Column("rocking_creep_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("rocking_creep_completed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_work_orders_rocking_creep_completed_by_id_users",
        "work_orders",
        "users",
        ["rocking_creep_completed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_work_orders_rocking_creep_completed_by_id_users",
        "work_orders",
        type_="foreignkey",
    )
    op.drop_column("work_orders", "rocking_creep_completed_by_id")
    op.drop_column("work_orders", "rocking_creep_completed_at")
    op.drop_column("work_orders", "is_rocking_creep_complete")
