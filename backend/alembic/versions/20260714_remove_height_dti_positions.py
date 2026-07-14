"""Remove height/DTI-position measurement columns (unused outside rocking/creep)

Height-position (H1-H4) capture was never used in practice — confirmed zero
rows with ``measurements.height_data`` populated. DTI hardware is used only
for the Rocking & Creep entry flow, which stores plain ``rocking_value`` /
``creep_value`` columns, not positional height data. Drops:

  - ``measurements.height_data`` (JSONB)
  - ``assembly_blade_records.assembly_dti_h1..h4`` and ``oh_dti_h1..h4``
    (the Assembly-side DTI tolerance-check columns)

Revision ID: f9e8d7c6b5a4
Revises: f2a3b4c5d6e7
Create Date: 2026-07-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f9e8d7c6b5a4'
down_revision: str = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("measurements", "height_data")

    for col in (
        "assembly_dti_h1", "assembly_dti_h2", "assembly_dti_h3", "assembly_dti_h4",
        "oh_dti_h1", "oh_dti_h2", "oh_dti_h3", "oh_dti_h4",
    ):
        op.drop_column("assembly_blade_records", col)


def downgrade() -> None:
    for col in (
        "oh_dti_h4", "oh_dti_h3", "oh_dti_h2", "oh_dti_h1",
        "assembly_dti_h4", "assembly_dti_h3", "assembly_dti_h2", "assembly_dti_h1",
    ):
        op.add_column(
            "assembly_blade_records",
            sa.Column(col, sa.Numeric(10, 4), nullable=True),
        )

    op.add_column(
        "measurements",
        sa.Column("height_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
