import { useCallback, useRef } from "react";
import type { GridColumn } from "@/store/bladeEntryStore";

const COLUMNS: GridColumn[] = ["melt_number", "weight"];

export interface GridKeyboardNavHandlers {
  /** Register/unregister an input's DOM node for a given (rowIndex, column). */
  registerCell: (rowIndex: number, column: GridColumn, el: HTMLInputElement | null) => void;
  /** Move focus (DOM + store) to a specific cell. */
  focusCell: (rowIndex: number, column: GridColumn) => void;
  /** Attach to each cell's onKeyDown. */
  handleKeyDown: (
    e: React.KeyboardEvent<HTMLInputElement>,
    rowIndex: number,
    column: GridColumn
  ) => void;
}

interface Options {
  rowCount: number;
  /** Called on Enter in an empty Melt Number cell — trigger OCR capture. */
  onTriggerOcr: (rowIndex: number) => void;
  /** Called on Enter in a populated cell that completes the row — confirm + autosave. */
  onConfirmRow: (rowIndex: number) => void;
  /** Called on F2 while focused on the Melt Number cell — open Russian keyboard. */
  onOpenRussianKeyboard: (rowIndex: number) => void;
}

/**
 * Owns cell-to-cell keyboard navigation for the 90-row grid via a flat ref
 * matrix (rowIndex x column). S.No / Weight(g) / Static Moment are plain
 * display cells (never registered here), so Tab naturally skips them.
 */
export function useGridKeyboardNav({
  rowCount,
  onTriggerOcr,
  onConfirmRow,
  onOpenRussianKeyboard,
}: Options): GridKeyboardNavHandlers {
  const refs = useRef<Map<string, HTMLInputElement>>(new Map());

  const key = (rowIndex: number, column: GridColumn) => `${rowIndex}:${column}`;

  const registerCell = useCallback((rowIndex: number, column: GridColumn, el: HTMLInputElement | null) => {
    const k = key(rowIndex, column);
    if (el) refs.current.set(k, el);
    else refs.current.delete(k);
  }, []);

  const focusCell = useCallback((rowIndex: number, column: GridColumn) => {
    const clamped = Math.max(0, Math.min(rowCount - 1, rowIndex));
    const el = refs.current.get(key(clamped, column));
    el?.focus();
    el?.select?.();
  }, [rowCount]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>, rowIndex: number, column: GridColumn) => {
      const input = e.currentTarget;

      if (e.key === "F2" && column === "melt_number") {
        e.preventDefault();
        onOpenRussianKeyboard(rowIndex);
        return;
      }

      if (e.key === "Enter") {
        e.preventDefault();
        if (column === "melt_number") {
          if (input.value.trim().length === 0) {
            onTriggerOcr(rowIndex);
          } else {
            focusCell(rowIndex, "weight");
          }
        } else {
          // weight column
          if (input.value.trim().length > 0) {
            onConfirmRow(rowIndex);
            focusCell(rowIndex + 1, "melt_number");
          }
        }
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        focusCell(rowIndex + 1, column);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        focusCell(rowIndex - 1, column);
        return;
      }

      if (e.key === "ArrowRight") {
        const atEnd = input.selectionStart === input.value.length && input.selectionEnd === input.value.length;
        if (atEnd) {
          const colIdx = COLUMNS.indexOf(column);
          const next = COLUMNS[colIdx + 1];
          if (next) {
            e.preventDefault();
            focusCell(rowIndex, next);
          }
        }
        return;
      }
      if (e.key === "ArrowLeft") {
        const atStart = input.selectionStart === 0 && input.selectionEnd === 0;
        if (atStart) {
          const colIdx = COLUMNS.indexOf(column);
          const prev = colIdx > 0 ? COLUMNS[colIdx - 1] : undefined;
          if (prev) {
            e.preventDefault();
            focusCell(rowIndex, prev);
          }
        }
        return;
      }
    },
    [focusCell, onTriggerOcr, onConfirmRow, onOpenRussianKeyboard]
  );

  return { registerCell, focusCell, handleKeyDown };
}
