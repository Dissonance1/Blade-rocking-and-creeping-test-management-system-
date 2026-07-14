import { memo } from "react";
import { Check, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/utils/cn";
import type { GridRowState, GridColumn } from "@/store/bladeEntryStore";
import ReadOnlyCell from "./cells/ReadOnlyCell";
import MeltNumberCell from "./cells/MeltNumberCell";
import WeightCell from "./cells/WeightCell";
import type { GridKeyboardNavHandlers } from "./hooks/useGridKeyboardNav";

interface GridRowProps {
  row: GridRowState;
  rowIndex: number;
  focusedRowIndex: number;
  focusedColumn: GridColumn;
  nav: GridKeyboardNavHandlers;
  onCellChange: (rowIndex: number, column: GridColumn, value: string) => void;
  onFocusCell: (rowIndex: number, column: GridColumn) => void;
  onRetrySave: (rowIndex: number) => void;
  onScanClick: (rowIndex: number) => void;
  onKeyboardClick: (rowIndex: number) => void;
  onLockWeight: (rowIndex: number) => void;
  onUnlockWeight: (rowIndex: number) => void;
}

function statusIndicator(row: GridRowState, onRetry: () => void) {
  switch (row.status) {
    case "saving":
      return <Loader2 className="w-4 h-4 animate-spin text-slate-400" />;
    case "saved":
      return <Check className="w-4 h-4 text-emerald-500" />;
    case "error":
      return (
        <button
          type="button"
          title={row.error_message ?? "Save failed — click to retry"}
          onClick={onRetry}
          className="text-red-500 hover:text-red-600"
        >
          <AlertCircle className="w-4 h-4" />
        </button>
      );
    default:
      return <span className="w-4 h-4 inline-block" />;
  }
}

function GridRow({
  row,
  rowIndex,
  focusedRowIndex,
  focusedColumn,
  nav,
  onCellChange,
  onFocusCell,
  onRetrySave,
  onScanClick,
  onKeyboardClick,
  onLockWeight,
  onUnlockWeight,
}: GridRowProps) {
  const isFocusedRow = rowIndex === focusedRowIndex;
  const meltFocused = isFocusedRow && focusedColumn === "melt_number";
  const weightFocused = isFocusedRow && focusedColumn === "weight";

  return (
    <div
      className={cn(
        "grid grid-cols-[3rem_1fr_1fr_1fr_1fr_2rem] gap-2 items-center px-2 py-1 rounded-md",
        isFocusedRow && "bg-orange-50/60 dark:bg-orange-500/5",
        row.locked && "opacity-90"
      )}
    >
      <ReadOnlyCell value={String(row.s_no).padStart(2, "0")} className="justify-center text-center font-mono" />

      <MeltNumberCell
        row={row}
        rowIndex={rowIndex}
        isFocused={meltFocused}
        registerRef={(el) => nav.registerCell(rowIndex, "melt_number", el)}
        onChange={(v) => onCellChange(rowIndex, "melt_number", v)}
        onKeyDown={(e) => nav.handleKeyDown(e, rowIndex, "melt_number")}
        onFocus={() => onFocusCell(rowIndex, "melt_number")}
        onScanClick={() => onScanClick(rowIndex)}
        onKeyboardClick={() => onKeyboardClick(rowIndex)}
      />

      <WeightCell
        row={row}
        rowIndex={rowIndex}
        isFocused={weightFocused}
        liveFromScale={false}
        registerRef={(el) => nav.registerCell(rowIndex, "weight", el)}
        onChange={(v) => onCellChange(rowIndex, "weight", v)}
        onKeyDown={(e) => nav.handleKeyDown(e, rowIndex, "weight")}
        onFocus={() => onFocusCell(rowIndex, "weight")}
        onLockWeight={() => onLockWeight(rowIndex)}
        onUnlockWeight={() => onUnlockWeight(rowIndex)}
      />

      <ReadOnlyCell value={row.weight_grams != null ? row.weight_grams.toFixed(2) : "—"} className="justify-end font-mono" />
      <ReadOnlyCell value={row.static_moment_gcm != null ? row.static_moment_gcm.toFixed(2) : "—"} className="justify-end font-mono" />

      <div className="flex items-center justify-center">{statusIndicator(row, () => onRetrySave(rowIndex))}</div>
    </div>
  );
}

export default memo(GridRow);
