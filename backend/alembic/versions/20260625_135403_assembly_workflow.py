"""assembly_workflow — add ASSEMBLY_RECEIVED / ASSEMBLY_VERIFIED blade statuses

Adds the two new BladeStatus values required for the Assembly station
receipt and verification flow (720 Hanger).

    SENT_TO_ASSEMBLY → ASSEMBLY_RECEIVED → ASSEMBLY_VERIFIED → SLOT_ASSIGNED

Revision ID: d7cdeadbb810
Revises: b2c3d4e5f6a7
Create Date: 2026-06-25 13:54:03.614892
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7cdeadbb810'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires each ADD VALUE to be its own statement.
    # IF NOT EXISTS prevents failure if the migration is re-applied.
    op.execute("ALTER TYPE bladestatus ADD VALUE IF NOT EXISTS 'ASSEMBLY_RECEIVED' AFTER 'SENT_TO_ASSEMBLY'")
    op.execute("ALTER TYPE bladestatus ADD VALUE IF NOT EXISTS 'ASSEMBLY_VERIFIED' AFTER 'ASSEMBLY_RECEIVED'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values natively.
    # To roll back: recreate the type without these values (data migration required).
    pass
