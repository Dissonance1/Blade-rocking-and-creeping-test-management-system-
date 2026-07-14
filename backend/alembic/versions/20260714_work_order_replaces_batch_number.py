"""Replace Batch Number with Work Order Number as the primary grouping key

Introduces a proper ``work_orders`` header table (one row per 90-blade,
single-blade-type set). ``blades.batch_number`` is removed in favor of
``blades.work_order_id`` (FK) + the existing ``blades.work_order_number``
denormalized column. ``batch_groups`` (an autofill cache, now fully
superseded by ``work_orders``) is dropped. ``batch_events`` is renamed to
``work_order_events`` with its ``batch_number`` column renamed to
``work_order_number``. ``assembly_batch_receipts.batch_number`` is renamed
to ``work_order_number``. ``measurements`` gets a unique
``(blade_id, measurement_type)`` constraint to support idempotent
per-row autosave upserts.

This is a clean schema change over dev/seed-only data (per product
decision, no production data exists yet) — existing blade/batch rows are
truncated rather than backfilled, since there is no way to derive a
single-blade-type 90-row Work Order from the old dual-type batch shape.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: str = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Dev/seed data only — clean reset instead of backfilling the old
    # dual-type batch shape into single-type work orders.
    op.execute(
        "TRUNCATE TABLE blades, batch_events, batch_groups, "
        "assembly_batch_receipts RESTART IDENTITY CASCADE"
    )

    # ------------------------------------------------------------------
    # 1. work_orders header table
    # ------------------------------------------------------------------
    op.create_table(
        "work_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_order_number", sa.String(64), nullable=False),
        sa.Column("shop_order_number", sa.String(64), nullable=False),
        sa.Column("part_number", sa.String(64), nullable=False),
        sa.Column(
            "blade_type",
            postgresql.ENUM("LPTR", "HPTR", name="bladetype", create_type=False),
            nullable=False,
        ),
        sa.Column("engine_number", sa.String(64), nullable=True),
        sa.Column("engine_hours", sa.String(64), nullable=False),
        sa.Column("component_hours", sa.String(64), nullable=True),
        sa.Column(
            "is_entry_complete", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("entry_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "entry_completed_by_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_by_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_work_orders_work_order_number", "work_orders",
        ["work_order_number"], unique=True,
    )

    # ------------------------------------------------------------------
    # 2. blades: drop batch_number/ocr_serial_number, add work_order_id
    # ------------------------------------------------------------------
    op.drop_constraint("uq_blade_batch_type_serial", "blades", type_="unique")
    op.drop_column("blades", "batch_number")
    op.drop_column("blades", "ocr_serial_number")
    op.add_column(
        "blades",
        sa.Column(
            "work_order_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_orders.id", ondelete="RESTRICT"), nullable=False,
        ),
    )
    op.create_index("ix_blades_work_order_id", "blades", ["work_order_id"])
    op.create_index("ix_blades_work_order_number", "blades", ["work_order_number"])
    op.create_unique_constraint(
        "uq_blade_workorder_serial", "blades", ["work_order_id", "serial_number"],
    )

    # ------------------------------------------------------------------
    # 3. measurements: unique (blade_id, measurement_type)
    # ------------------------------------------------------------------
    op.drop_index("ix_measurements_blade_type", table_name="measurements")
    op.create_unique_constraint(
        "uq_measurement_blade_type", "measurements", ["blade_id", "measurement_type"],
    )

    # ------------------------------------------------------------------
    # 4. batch_groups: drop (fully superseded by work_orders)
    # ------------------------------------------------------------------
    op.drop_table("batch_groups")

    # ------------------------------------------------------------------
    # 5. batch_events -> work_order_events
    # ------------------------------------------------------------------
    op.rename_table("batch_events", "work_order_events")
    op.alter_column(
        "work_order_events", "batch_number", new_column_name="work_order_number",
    )
    op.drop_index("ix_batch_events_batch_ts", table_name="work_order_events")
    op.create_index(
        "ix_work_order_events_wo_ts", "work_order_events",
        ["work_order_number", "timestamp"],
    )

    # ------------------------------------------------------------------
    # 6. assembly_batch_receipts: rename batch_number -> work_order_number
    # ------------------------------------------------------------------
    op.drop_index(
        "ix_assembly_batch_receipts_batch_number", table_name="assembly_batch_receipts",
    )
    op.alter_column(
        "assembly_batch_receipts", "batch_number", new_column_name="work_order_number",
    )
    op.create_index(
        "ix_assembly_batch_receipts_work_order_number", "assembly_batch_receipts",
        ["work_order_number"], unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assembly_batch_receipts_work_order_number",
        table_name="assembly_batch_receipts",
    )
    op.alter_column(
        "assembly_batch_receipts", "work_order_number", new_column_name="batch_number",
    )
    op.create_index(
        "ix_assembly_batch_receipts_batch_number", "assembly_batch_receipts",
        ["batch_number"], unique=True,
    )

    op.drop_index("ix_work_order_events_wo_ts", table_name="work_order_events")
    op.alter_column(
        "work_order_events", "work_order_number", new_column_name="batch_number",
    )
    op.create_index(
        "ix_batch_events_batch_ts", "work_order_events", ["batch_number", "timestamp"],
    )
    op.rename_table("work_order_events", "batch_events")

    op.create_table(
        "batch_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_number", sa.String(64), nullable=False),
        sa.Column("work_order_number", sa.String(64), nullable=True),
        sa.Column("part_number", sa.String(64), nullable=True),
        sa.Column("engine_number", sa.String(64), nullable=True),
        sa.Column("nomenclature", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_batch_groups_batch_number", "batch_groups", ["batch_number"], unique=True,
    )

    op.drop_constraint("uq_measurement_blade_type", "measurements", type_="unique")
    op.create_index(
        "ix_measurements_blade_type", "measurements", ["blade_id", "measurement_type"],
    )

    op.drop_constraint("uq_blade_workorder_serial", "blades", type_="unique")
    op.drop_index("ix_blades_work_order_number", table_name="blades")
    op.drop_index("ix_blades_work_order_id", table_name="blades")
    op.drop_column("blades", "work_order_id")
    op.add_column("blades", sa.Column("ocr_serial_number", sa.String(64), nullable=True))
    op.add_column("blades", sa.Column("batch_number", sa.String(64), nullable=True))
    op.create_index("ix_blades_batch_number", "blades", ["batch_number"])
    op.create_unique_constraint(
        "uq_blade_batch_type_serial", "blades",
        ["batch_number", "blade_type", "serial_number"],
    )

    op.drop_index("ix_work_orders_work_order_number", table_name="work_orders")
    op.drop_table("work_orders")
