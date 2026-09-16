"""partial_unique_email_username_active_only

Revision ID: 04f1cc3f627f
Revises: 8b9651c496c5
Create Date: 2026-09-16 07:25:36.819929

Scope note: `alembic revision --autogenerate` also picked up pre-existing,
unrelated schema drift (batch_events -> work_order_events index renames,
dropped server defaults on work_orders, column comments) — stripped per
CLAUDE.md's guidance so this migration only touches the users table.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04f1cc3f627f'
down_revision: Union[str, None] = '8b9651c496c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A soft-deleted user (deleted_at set) must free up their email/username
    # for reuse — application code already assumed this (see the uniqueness
    # pre-checks in create_user), but the plain unique index enforced
    # uniqueness across ALL rows regardless of deleted_at, causing a raw
    # IntegrityError/500 on re-creating a user with a previously-deleted
    # email or username. Replace with partial unique indexes scoped to
    # active (non-deleted) rows only.
    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_username', table_name='users')
    op.create_index('ix_users_email_unique_active', 'users', ['email'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_users_username_unique_active', 'users', ['username'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))


def downgrade() -> None:
    op.drop_index('ix_users_username_unique_active', table_name='users', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_users_email_unique_active', table_name='users', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
