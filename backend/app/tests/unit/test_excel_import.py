"""
Unit tests for app.services.excel_import.parse_work_order_rows.

Pure Python — no DB. Builds small in-memory .xlsx workbooks with openpyxl
and asserts on the parsed (s_no, WorkOrderRowUpdate) pairs / errors.
"""

from __future__ import annotations

import io

import openpyxl
import pytest

from app.core.constants import BLADES_PER_WORK_ORDER
from app.services.excel_import import parse_work_order_rows


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    """Build a minimal .xlsx from a list of rows (first row = header)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.unit
def test_parses_valid_rows_with_standard_headers() -> None:
    data = _xlsx_bytes(
        [
            ["S.No", "Melt Number", "Weight"],
            [1, "MELT-001", 157.35],
            [2, "MELT-002", 155.58],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert parsed.errors == []
    assert len(parsed.rows) == 2
    s_no, row = parsed.rows[0]
    assert s_no == 1
    assert row.melt_number == "MELT-001"
    assert row.raw_weight == pytest.approx(157.35)


@pytest.mark.unit
def test_scans_past_merged_title_row_for_header() -> None:
    """Real shop-floor sheets (HPTR_0083.xlsx) have a title banner on row 1."""
    data = _xlsx_bytes(
        [
            ["HPTR 0083", None, None, None],
            ["Blade Sl No.", "Melt No.", "W", "Weight in gm"],
            [1, "166H631", 157.35, 247.0395],
            [2, "167^79", 155.58, 244.2606],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert parsed.errors == []
    assert len(parsed.rows) == 2
    s_no, row = parsed.rows[0]
    assert s_no == 1
    assert row.melt_number == "166H631"
    # The raw "W" column is imported, not the computed "Weight in gm" column.
    assert row.raw_weight == pytest.approx(157.35)


@pytest.mark.unit
def test_weight_in_gm_alone_is_treated_as_raw() -> None:
    """
    HPTR_16-96-317.xls has no short "W"/"Weight" column at all — "Weight in
    gm" IS the raw scale reading there, with "Actual Weight in gm" as the
    separate computed column. Without a tier-1 alternative present, "Weight
    in gm" must be trusted as raw rather than ignored.
    """
    data = _xlsx_bytes(
        [
            ["S.No", "Melt No.", "Weight in gm", "Actual Weight in gm", "Static Moment"],
            [1, "MELT-001", 158.42, 248.7194, 4974.388],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert parsed.errors == []
    assert len(parsed.rows) == 1
    _, row = parsed.rows[0]
    assert row.raw_weight == pytest.approx(158.42)


@pytest.mark.unit
def test_multi_block_header_parses_both_blocks() -> None:
    """
    Some legacy sheets print two blade blocks side by side on one page —
    the same headers repeated twice across disjoint S.No ranges.
    """
    data = _xlsx_bytes(
        [
            ["S.No", "Melt No.", "Weight", None, "S.No", "Melt No.", "Weight"],
            [1, "MELT-001", 100.0, None, 46, "MELT-046", 200.0],
            [2, "MELT-002", 110.0, None, 47, "MELT-047", 210.0],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert parsed.errors == []
    s_nos = sorted(s for s, _ in parsed.rows)
    assert s_nos == [1, 2, 46, 47]
    by_s_no = dict(parsed.rows)
    assert by_s_no[46].melt_number == "MELT-046"
    assert by_s_no[46].raw_weight == pytest.approx(200.0)


@pytest.mark.unit
def test_duplicate_s_no_across_blocks_still_detected() -> None:
    data = _xlsx_bytes(
        [
            ["S.No", "Melt No.", "Weight", None, "S.No", "Melt No.", "Weight"],
            [1, "MELT-001", 100.0, None, 1, "MELT-DUPLICATE", 200.0],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert len(parsed.rows) == 1
    assert parsed.rows[0][1].melt_number == "MELT-001"
    assert len(parsed.errors) == 1
    assert "duplicate" in parsed.errors[0].message.lower()


@pytest.mark.unit
def test_no_header_row_found_returns_error() -> None:
    data = _xlsx_bytes([["foo", "bar"], ["baz", "qux"]])
    parsed = parse_work_order_rows(data)
    assert parsed.rows == []
    assert len(parsed.errors) == 1
    assert "header" in parsed.errors[0].message.lower()


@pytest.mark.unit
def test_out_of_range_s_no_is_skipped_but_others_still_import() -> None:
    data = _xlsx_bytes(
        [
            ["S.No", "Melt Number", "Weight"],
            [1, "MELT-001", 100.0],
            [BLADES_PER_WORK_ORDER + 1, "MELT-BAD", 100.0],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert len(parsed.rows) == 1
    assert parsed.rows[0][0] == 1
    assert len(parsed.errors) == 1
    assert "out of range" in parsed.errors[0].message.lower()


@pytest.mark.unit
def test_duplicate_s_no_reported_as_error() -> None:
    data = _xlsx_bytes(
        [
            ["S.No", "Melt Number", "Weight"],
            [1, "MELT-001", 100.0],
            [1, "MELT-DUPLICATE", 200.0],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert len(parsed.rows) == 1
    assert parsed.rows[0][1].melt_number == "MELT-001"
    assert len(parsed.errors) == 1
    assert "duplicate" in parsed.errors[0].message.lower()


@pytest.mark.unit
def test_non_numeric_weight_reported_as_error() -> None:
    data = _xlsx_bytes(
        [
            ["S.No", "Melt Number", "Weight"],
            [1, "MELT-001", "not-a-number"],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert parsed.rows == []
    assert len(parsed.errors) == 1
    assert "not a number" in parsed.errors[0].message.lower()


@pytest.mark.unit
def test_blank_rows_skipped_silently() -> None:
    data = _xlsx_bytes(
        [
            ["S.No", "Melt Number", "Weight"],
            [1, "MELT-001", 100.0],
            [None, None, None],
            [None, None, None],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert len(parsed.rows) == 1
    assert parsed.errors == []


@pytest.mark.unit
def test_partial_row_leaves_missing_fields_none() -> None:
    """A row with only Melt Number (no Weight) is valid — matches manual autosave's partial-save semantics."""
    data = _xlsx_bytes(
        [
            ["S.No", "Melt Number", "Weight"],
            [1, "MELT-001", None],
        ]
    )
    parsed = parse_work_order_rows(data)
    assert len(parsed.rows) == 1
    _, row = parsed.rows[0]
    assert row.melt_number == "MELT-001"
    assert row.raw_weight is None
