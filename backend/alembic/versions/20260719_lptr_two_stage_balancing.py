"""lptr_two_stage_balancing — empty rotor reading, balancing checks, manual corrections

Adds the tables backing the LPTR two-stage (46+44 blade) slot allocation
workflow: the empty-rotor unbalance reading taken before any blades are
installed, an append-only log of measured-unbalance balancing checks per
stage, and a typed log of operator manual corrections (rearrangement,
balancing adjustment, manufacturer replacement request). Also adds a
nullable ``stage`` column to ``slot_allocations`` recording which of the
two stages an active LPTR allocation came from (null for HPTR/legacy rows).

Revision ID: 1a2b3c4d5e6f
Revises: 9f4c2e7a1d08
Create Date: 2026-07-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = '9f4c2e7a1d08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guarded with existence checks: in dev environments (ENVIRONMENT != "prod"),
    # app startup's init_db() already runs Base.metadata.create_all(), which may
    # create these brand-new tables before this migration ever runs. That
    # helper only creates missing tables though — it never alters an existing
    # table — so the stage column ALTER below always still needs to run.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ------------------------------------------------------------------
    # slot_allocations.stage
    # ------------------------------------------------------------------
    existing_columns = {c["name"] for c in inspector.get_columns("slot_allocations")}
    if "stage" not in existing_columns:
        op.add_column("slot_allocations", sa.Column("stage", sa.Integer(), nullable=True))

    # ------------------------------------------------------------------
    # lptr_empty_rotor_readings
    # ------------------------------------------------------------------
    if "lptr_empty_rotor_readings" not in existing_tables:
        op.create_table(
            "lptr_empty_rotor_readings",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("work_order_number", sa.String(64), nullable=False),
            sa.Column("unbalance_slot", sa.Integer(), nullable=False),
            sa.Column("unbalance_value", sa.Numeric(12, 4), nullable=False),
            sa.Column(
                "recorded_by_id", postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
            ),
            sa.Column(
                "recorded_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
        )
        op.create_index(
            "ix_lptr_empty_rotor_readings_work_order_number",
            "lptr_empty_rotor_readings", ["work_order_number"], unique=True,
        )

    # ------------------------------------------------------------------
    # lptr_balancing_checks
    # ------------------------------------------------------------------
    if "lptr_balancing_checks" not in existing_tables:
        op.create_table(
            "lptr_balancing_checks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("work_order_number", sa.String(64), nullable=False),
            sa.Column("stage", sa.Integer(), nullable=False),
            sa.Column("measured_unbalance", sa.Numeric(12, 4), nullable=False),
            sa.Column("is_pass", sa.Boolean(), nullable=False),
            sa.Column("remarks", sa.Text(), nullable=True),
            sa.Column(
                "recorded_by_id", postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
            ),
            sa.Column(
                "recorded_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.CheckConstraint("stage IN (1, 2)", name="ck_lptr_balancing_checks_stage"),
        )
        op.create_index(
            "ix_lptr_balancing_checks_wo_stage",
            "lptr_balancing_checks", ["work_order_number", "stage"],
        )

    # ------------------------------------------------------------------
    # lptr_manual_corrections
    # ------------------------------------------------------------------
    if "lptr_manual_corrections" not in existing_tables:
        op.create_table(
            "lptr_manual_corrections",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("work_order_number", sa.String(64), nullable=False),
            sa.Column("stage", sa.Integer(), nullable=False),
            sa.Column(
                "correction_type",
                postgresql.ENUM(
                    "REARRANGEMENT", "BALANCING_ADJUSTMENT", "MANUFACTURER_REPLACEMENT_REQUEST",
                    name="lptrcorrectiontype", create_type=True,
                ),
                nullable=False,
            ),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "blade_id", postgresql.UUID(as_uuid=True),
                sa.ForeignKey("blades.id", ondelete="SET NULL"), nullable=True,
            ),
            sa.Column("slot_number", sa.String(32), nullable=True),
            sa.Column(
                "recorded_by_id", postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
            ),
            sa.Column(
                "recorded_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
        )
        op.create_index(
            "ix_lptr_manual_corrections_wo_stage",
            "lptr_manual_corrections", ["work_order_number", "stage"],
        )


def downgrade() -> None:
    op.drop_index("ix_lptr_manual_corrections_wo_stage", table_name="lptr_manual_corrections")
    op.drop_table("lptr_manual_corrections")
    op.execute("DROP TYPE IF EXISTS lptrcorrectiontype")

    op.drop_index("ix_lptr_balancing_checks_wo_stage", table_name="lptr_balancing_checks")
    op.drop_table("lptr_balancing_checks")

    op.drop_index(
        "ix_lptr_empty_rotor_readings_work_order_number",
        table_name="lptr_empty_rotor_readings",
    )
    op.drop_table("lptr_empty_rotor_readings")

    op.drop_column("slot_allocations", "stage")
