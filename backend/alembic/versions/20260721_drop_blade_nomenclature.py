"""drop_blade_nomenclature — remove the redundant nomenclature column

`Blade.nomenclature` was always the same hardcoded string per blade_type
(e.g. "HP Turbine Blade Stage 1") — fully redundant with `blade_type`
(LPTR/HPTR), which every Work Order/Blade already carries. Dropping it.

Revision ID: 7f8e9d0c1b2a
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f8e9d0c1b2a'
down_revision: Union[str, None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("blades")}
    if "nomenclature" in columns:
        op.drop_column("blades", "nomenclature")


def downgrade() -> None:
    op.add_column("blades", sa.Column("nomenclature", sa.String(length=128), nullable=True))
