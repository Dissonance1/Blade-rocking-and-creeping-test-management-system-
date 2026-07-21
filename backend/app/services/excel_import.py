"""
Parses an uploaded Work Order sheet (.xlsx or legacy .xls) into grid-entry
rows.

Uses pandas' read_excel, which picks the right engine automatically —
openpyxl for .xlsx, xlrd for legacy .xls — so both formats go through the
same parsing logic below.

Real shop-floor sheets (e.g. HPTR_0083.xlsx) have a merged title banner on
row 1 and the actual header labels on row 2 — this scans for whichever row
looks like a header rather than assuming row 1. Only S.No / Melt Number /
Weight (the raw scale reading) are read; computed columns like "Weight in
gm" / "Static Moment" are recomputed server-side exactly as they are for
manual entry, and "Rocking" is entered later via Rocking & Creep Entry —
both are ignored here if present.

Some legacy .xls sheets (e.g. HPTR_16-96-317.xls) print two blade blocks
side by side on one printed page — the same S.No/Melt/Weight header labels
repeated twice across the row, covering two disjoint S.No ranges (e.g.
1-45 and 46-90). This scans for every such repeated block in the header
row and parses each one, rather than assuming a single block.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field

import pandas as pd

from app.core.constants import BLADES_PER_WORK_ORDER
from app.schemas.work_order import WorkOrderRowUpdate

_S_NO_ALIASES = {"s.no", "sl.no", "s no", "sno", "serial no", "serial number", "blade sl no."}
_MELT_ALIASES = {"melt number", "melt no", "melt no.", "melt_number"}

# Real shop-floor sheets disagree on which header text means "raw scale
# reading" vs. "server-computed weight": HPTR_0083.xlsx uses "W" for raw and
# "Weight in gm" for the computed value; HPTR_16-96-317.xls has no short
# column at all — "Weight in gm" IS the raw one there, with "Actual Weight in
# gm" as computed. So tier 1 (short/explicit-raw forms) wins whenever present
# in the same block; "weight in gm"-style tier 2 is only trusted as raw when
# no tier-1 column exists alongside it.
_RAW_WEIGHT_TIER1 = {"weight", "wt", "weight (raw)", "weight_gm", "w"}
_RAW_WEIGHT_TIER2 = {"weight in gm", "weight in grams", "weight gm"}

_MAX_HEADER_SCAN_ROWS = 5


@dataclass
class ImportRowError:
    row: int
    message: str


@dataclass
class ParsedImport:
    rows: list[tuple[int, WorkOrderRowUpdate]] = field(default_factory=list)
    errors: list[ImportRowError] = field(default_factory=list)


def _normalize_header(cell_value: object) -> str:
    text = str(cell_value or "")
    return re.sub(r"\s+", " ", text).strip().lower()


def _clean_cell(value: object) -> object:
    """pandas represents blank cells as NaN — normalize to None."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _find_header_blocks(rows_data: list[tuple]) -> tuple[int, list[dict[str, int]]] | None:
    """
    Scan the first few rows for one containing S.No plus at least one of
    Melt Number/Weight — possibly repeated as multiple side-by-side blocks
    on the same row. Returns (0-based row index into rows_data, list of
    {field_name: 0-based column index} — one dict per block), or None if no
    header row was found.
    """
    for row_index, row in enumerate(rows_data[:_MAX_HEADER_SCAN_ROWS]):
        blocks: list[dict[str, int]] = []
        n = len(row)
        col = 0
        while col < n:
            s_no_col: int | None = None
            for c in range(col, n):
                if _normalize_header(row[c]) in _S_NO_ALIASES:
                    s_no_col = c
                    break
            if s_no_col is None:
                break

            # This block's columns end at the next S.No column (start of the
            # next repeated block) or the end of the row.
            block_end = n
            for c in range(s_no_col + 1, n):
                if _normalize_header(row[c]) in _S_NO_ALIASES:
                    block_end = c
                    break

            melt_col = weight_tier1_col = weight_tier2_col = None
            for c in range(s_no_col, block_end):
                normalized = _normalize_header(row[c])
                if not normalized:
                    continue
                if melt_col is None and normalized in _MELT_ALIASES:
                    melt_col = c
                if weight_tier1_col is None and normalized in _RAW_WEIGHT_TIER1:
                    weight_tier1_col = c
                if weight_tier2_col is None and normalized in _RAW_WEIGHT_TIER2:
                    weight_tier2_col = c

            weight_col = weight_tier1_col if weight_tier1_col is not None else weight_tier2_col
            if melt_col is not None or weight_col is not None:
                block: dict[str, int] = {"s_no": s_no_col}
                if melt_col is not None:
                    block["melt_number"] = melt_col
                if weight_col is not None:
                    block["raw_weight"] = weight_col
                blocks.append(block)

            col = block_end

        if blocks:
            return row_index, blocks
    return None


def _parse_block(
    rows_data: list[tuple],
    header_row_index: int,
    columns: dict[str, int],
    seen_s_nos: set[int],
    result: ParsedImport,
    block_label: str,
) -> None:
    s_no_col = columns["s_no"]
    melt_col = columns.get("melt_number")
    weight_col = columns.get("raw_weight")

    for offset, row in enumerate(rows_data[header_row_index + 1 :]):
        row_num = header_row_index + 2 + offset  # 1-based file row number, for error messages
        s_no_cell = row[s_no_col] if s_no_col < len(row) else None
        melt_cell = row[melt_col] if melt_col is not None and melt_col < len(row) else None
        weight_cell = row[weight_col] if weight_col is not None and weight_col < len(row) else None

        if s_no_cell is None and melt_cell is None and weight_cell is None:
            continue  # fully blank row — skip silently

        if s_no_cell is None:
            result.errors.append(ImportRowError(row=row_num, message=f"Missing S.No{block_label}"))
            continue

        try:
            s_no = int(float(s_no_cell))
        except (TypeError, ValueError):
            result.errors.append(ImportRowError(row=row_num, message=f"S.No '{s_no_cell}' is not a number{block_label}"))
            continue

        if not 1 <= s_no <= BLADES_PER_WORK_ORDER:
            result.errors.append(
                ImportRowError(
                    row=row_num,
                    message=f"S.No {s_no} out of range (must be 1-{BLADES_PER_WORK_ORDER}){block_label}",
                )
            )
            continue

        if s_no in seen_s_nos:
            result.errors.append(ImportRowError(row=row_num, message=f"Duplicate S.No {s_no}{block_label}"))
            continue

        melt_number = str(melt_cell).strip() if melt_cell is not None and str(melt_cell).strip() else None

        raw_weight: float | None = None
        if weight_cell is not None and str(weight_cell).strip():
            try:
                raw_weight = float(weight_cell)
            except (TypeError, ValueError):
                result.errors.append(
                    ImportRowError(row=row_num, message=f"Weight '{weight_cell}' on S.No {s_no} is not a number{block_label}")
                )
                continue
            if raw_weight < 0:
                result.errors.append(
                    ImportRowError(row=row_num, message=f"Weight on S.No {s_no} must not be negative{block_label}")
                )
                continue

        seen_s_nos.add(s_no)
        result.rows.append((s_no, WorkOrderRowUpdate(melt_number=melt_number, raw_weight=raw_weight)))


def parse_work_order_rows(file_bytes: bytes) -> ParsedImport:
    """
    Parse an uploaded .xlsx/.xls's first worksheet into (s_no,
    WorkOrderRowUpdate) pairs plus a list of per-row errors. Bad rows are
    skipped and reported; good rows are still returned (partial success,
    not all-or-nothing).
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None, dtype=object)
    except Exception as exc:  # noqa: BLE001
        return ParsedImport(
            errors=[ImportRowError(row=0, message=f"Could not read file as Excel (.xlsx/.xls): {exc}")]
        )

    rows_data: list[tuple] = [
        tuple(_clean_cell(v) for v in row) for row in df.itertuples(index=False, name=None)
    ]

    header_match = _find_header_blocks(rows_data)
    if header_match is None:
        return ParsedImport(
            errors=[ImportRowError(row=0, message="No S.No / Melt Number / Weight header row found in the first 5 rows.")]
        )
    header_row_index, blocks = header_match

    result = ParsedImport()
    seen_s_nos: set[int] = set()
    multi_block = len(blocks) > 1
    for i, columns in enumerate(blocks):
        block_label = f" (block {i + 1})" if multi_block else ""
        _parse_block(rows_data, header_row_index, columns, seen_s_nos, result, block_label)

    return result
