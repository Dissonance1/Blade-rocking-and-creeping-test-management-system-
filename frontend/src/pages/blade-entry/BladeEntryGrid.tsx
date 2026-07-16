import { useCallback, useEffect, useRef, useState } from "react";
import {
  Wifi,
  WifiOff,
  Loader2,
  Check,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import CameraModal from "@/components/common/CameraModal";
import RussianKeyboard from "@/components/common/RussianKeyboard";
import { useWeighingSocket } from "@/hooks/useWeighingSocket";
import { extractApiError } from "@/services/api";
import { ocrService } from "@/services/ocrService";
import {
  workOrderService,
  type WorkOrderCompleteValidationError,
} from "@/services/workOrderService";
import { useBladeEntryStore, BLADES_PER_WORK_ORDER } from "@/store/bladeEntryStore";
import { useGridKeyboardNav } from "./hooks/useGridKeyboardNav";
import GridRow from "./GridRow";
import CompleteWorkOrderDialog from "./CompleteWorkOrderDialog";

const AUTOSAVE_DEBOUNCE_MS = 600;
const SAVE_RETRY_DELAYS_MS = [500, 1500, 4000];

export default function BladeEntryGrid() {
  const {
    commonInfo,
    rows,
    focusedRowIndex,
    focusedColumn,
    isEntryComplete,
    completeDialogOpen,
    completeErrors,
    setCellValue,
    applyOcrResult,
    lockRowWeight,
    unlockRow,
    markRowSaving,
    markRowSaved,
    markRowError,
    focusCell,
    openCompleteDialog,
    closeCompleteDialog,
    markEntryComplete,
    applyServerRow,
  } = useBladeEntryStore();

  const workOrderNumber = commonInfo.work_order_number;

  // ── Single shared weighing-socket + camera + RU keyboard for the whole grid ──
  const { currentReading, status: scaleStatus, clearReading } = useWeighingSocket();

  const [cameraTargetRow, setCameraTargetRow] = useState<number | null>(null);
  const [keyboardTargetRow, setKeyboardTargetRow] = useState<number | null>(null);
  const [completing, setCompleting] = useState(false);

  const saveTimersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const inFlightRef = useRef<Set<number>>(new Set());

  // ── Autosave: debounced per row, retried on failure, never blocks cursor ────
  const saveRow = useCallback(
    async (rowIndex: number, attempt = 0) => {
      const row = useBladeEntryStore.getState().rows[rowIndex];
      if (!row || row.locked) return;
      if (inFlightRef.current.has(rowIndex)) return;
      inFlightRef.current.add(rowIndex);
      markRowSaving(rowIndex);
      try {
        const result = await workOrderService.saveRow(workOrderNumber, row.s_no, {
          melt_number: row.melt_number,
          ocr_melt_number: row.ocr_melt_number || null,
          raw_weight: row.raw_weight ? parseFloat(row.raw_weight) : null,
        });
        applyServerRow(result);
        markRowSaved(rowIndex);
      } catch (err) {
        if (attempt < SAVE_RETRY_DELAYS_MS.length) {
          inFlightRef.current.delete(rowIndex);
          setTimeout(() => void saveRow(rowIndex, attempt + 1), SAVE_RETRY_DELAYS_MS[attempt]);
          return;
        }
        markRowError(rowIndex, extractApiError(err));
      } finally {
        inFlightRef.current.delete(rowIndex);
      }
    },
    [workOrderNumber, markRowSaving, markRowSaved, markRowError, applyServerRow]
  );

  const scheduleSave = useCallback(
    (rowIndex: number, immediate = false) => {
      const timers = saveTimersRef.current;
      const existing = timers.get(rowIndex);
      if (existing) clearTimeout(existing);
      if (immediate) {
        void saveRow(rowIndex);
        timers.delete(rowIndex);
        return;
      }
      timers.set(
        rowIndex,
        setTimeout(() => {
          timers.delete(rowIndex);
          void saveRow(rowIndex);
        }, AUTOSAVE_DEBOUNCE_MS)
      );
    },
    [saveRow]
  );

  const handleCellChange = useCallback(
    (rowIndex: number, column: "melt_number" | "weight", value: string) => {
      const readyToSave = setCellValue(rowIndex, column, value);
      if (readyToSave) scheduleSave(rowIndex);
    },
    [setCellValue, scheduleSave]
  );

  // ── Keyboard nav ─────────────────────────────────────────────────────────────
  const nav = useGridKeyboardNav({
    rowCount: rows.length,
    onTriggerOcr: (rowIndex) => setCameraTargetRow(rowIndex),
    onConfirmRow: (rowIndex) => scheduleSave(rowIndex, true),
    onOpenRussianKeyboard: (rowIndex) => setKeyboardTargetRow(rowIndex),
  });

  // ── Lock weight: finalize the row's reading, then advance and open the
  //    camera for the next row (manual capture — no autoCapture) ────────────
  const handleLockWeight = useCallback(
    (rowIndex: number) => {
      lockRowWeight(rowIndex);
      scheduleSave(rowIndex, true);
      clearReading();
      const nextRow = Math.min(rowIndex + 1, rows.length - 1);
      focusCell(nextRow, "melt_number");
      nav.focusCell(nextRow, "melt_number");
      setCameraTargetRow(nextRow);
    },
    [lockRowWeight, scheduleSave, clearReading, focusCell, rows.length, nav]
  );

  // ── Unlock: re-enable editing on a previously-locked row without
  //    touching focus/camera behavior ─────────────────────────────────────────
  const handleUnlockWeight = useCallback(
    (rowIndex: number) => {
      unlockRow(rowIndex);
      focusCell(rowIndex, "weight");
      nav.focusCell(rowIndex, "weight");
    },
    [unlockRow, focusCell, nav]
  );

  // Focus the store's current cell on mount / when it changes externally (e.g. resume)
  useEffect(() => {
    nav.focusCell(focusedRowIndex, focusedColumn);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Route the live scale reading into the focused row ───────────────────────
  useEffect(() => {
    if (!currentReading) return;
    const state = useBladeEntryStore.getState();
    const row = state.rows[state.focusedRowIndex];
    if (!row || row.locked) return;
    const readyToSave = setCellValue(state.focusedRowIndex, "weight", String(currentReading.value));
    if (readyToSave) scheduleSave(state.focusedRowIndex);
    clearReading();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentReading]);

  // ── Warn on unload while a save is pending ──────────────────────────────────
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      const hasPending = useBladeEntryStore
        .getState()
        .rows.some((r) => r.status === "dirty" || r.status === "saving");
      if (hasPending) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);

  // ── OCR capture ──────────────────────────────────────────────────────────────
  // Keeps the raw OCR detection (ocr_melt_number) separate from the editable
  // ground-truth cell (melt_number) so the two can be compared later, and
  // links the scanned image to this blade so it isn't an orphaned file.
  const handleOcrCapture = useCallback(
    async (file: File) => {
      const rowIndex = cameraTargetRow;
      if (rowIndex == null) return;
      try {
        const result = await ocrService.scanMelt(file);
        const readyToSave = applyOcrResult(rowIndex, result.value);
        const bladeId = useBladeEntryStore.getState().rows[rowIndex]?.blade_id;
        if (bladeId) {
          ocrService
            .attachScan(bladeId, result.scan_id, "melt_number", result.value, result.confidence)
            .catch(() => {
              // Non-fatal — the scanned value is already in the grid; losing the
              // image link shouldn't block data entry.
            });
        }
        if (readyToSave) scheduleSave(rowIndex);
      } finally {
        setCameraTargetRow(null);
        nav.focusCell(rowIndex, "melt_number");
      }
    },
    [cameraTargetRow, applyOcrResult, scheduleSave, nav]
  );

  // ── Russian keyboard ─────────────────────────────────────────────────────────
  const handleRussianConfirm = useCallback(
    (value: string) => {
      const rowIndex = keyboardTargetRow;
      if (rowIndex == null) return;
      const readyToSave = setCellValue(rowIndex, "melt_number", value);
      if (readyToSave) scheduleSave(rowIndex);
      setKeyboardTargetRow(null);
      nav.focusCell(rowIndex, "melt_number");
    },
    [keyboardTargetRow, setCellValue, scheduleSave, nav]
  );

  // ── Retry ─────────────────────────────────────────────────────────────────────
  const retryAllFailed = useCallback(() => {
    rows.forEach((r, idx) => {
      if (r.status === "error") void saveRow(idx);
    });
  }, [rows, saveRow]);

  // ── Complete ──────────────────────────────────────────────────────────────────
  const handleComplete = useCallback(async () => {
    setCompleting(true);
    try {
      await workOrderService.complete(workOrderNumber);
      markEntryComplete();
    } catch (err) {
      // This backend's global HTTPException handler wraps `detail` under a
      // `message` field (not FastAPI's default `{"detail": ...}` shape) —
      // see app/main.py's http_exception_handler.
      const message = (err as { response?: { data?: { message?: WorkOrderCompleteValidationError | string } } })
        ?.response?.data?.message;
      const parsed: WorkOrderCompleteValidationError =
        typeof message === "string" ? { message } : message ?? { message: "Could not complete Work Order." };
      openCompleteDialog(parsed);
    } finally {
      setCompleting(false);
    }
  }, [workOrderNumber, markEntryComplete, openCompleteDialog]);

  const jumpToRow = useCallback(
    (sNo: number) => {
      closeCompleteDialog();
      const rowIndex = sNo - 1;
      focusCell(rowIndex, "melt_number");
      setTimeout(() => nav.focusCell(rowIndex, "melt_number"), 50);
    },
    [closeCompleteDialog, focusCell, nav]
  );

  const savedCount = rows.filter((r) => r.status === "saved").length;
  const errorCount = rows.filter((r) => r.status === "error").length;

  return (
    <div className="flex flex-col h-full">
      <CameraModal
        open={cameraTargetRow != null}
        fieldLabel={cameraTargetRow != null ? `Melt Number — Row ${cameraTargetRow + 1}` : "Melt Number"}
        onCapture={(file) => void handleOcrCapture(file)}
        onClose={() => {
          setCameraTargetRow(null);
          if (cameraTargetRow != null) nav.focusCell(cameraTargetRow, "melt_number");
        }}
      />
      {keyboardTargetRow != null && (
        <RussianKeyboard
          initialValue={rows[keyboardTargetRow]?.melt_number ?? ""}
          onConfirm={handleRussianConfirm}
          onClose={() => {
            const idx = keyboardTargetRow;
            setKeyboardTargetRow(null);
            if (idx != null) nav.focusCell(idx, "melt_number");
          }}
        />
      )}
      <CompleteWorkOrderDialog
        open={completeDialogOpen}
        errors={completeErrors}
        submitting={completing}
        onJumpToRow={jumpToRow}
        onClose={closeCompleteDialog}
        onRetry={() => void handleComplete()}
      />

      {/* Header bar */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-2 pb-2">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-semibold text-slate-900 dark:text-white">
            {commonInfo.work_order_number}
          </span>
          <span className="text-slate-400">·</span>
          <span className="text-slate-500 dark:text-slate-400">{commonInfo.blade_type}</span>
          <span className="text-slate-400">·</span>
          <span className="text-slate-500 dark:text-slate-400">
            {savedCount}/{BLADES_PER_WORK_ORDER} saved
          </span>
          {scaleStatus === "connected" && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
              <Wifi className="w-3 h-3" /> Scale live
            </span>
          )}
          {scaleStatus !== "connected" && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400">
              {scaleStatus === "connecting" ? <Loader2 className="w-3 h-3 animate-spin" /> : <WifiOff className="w-3 h-3" />}
              {scaleStatus === "connecting" ? "Connecting…" : "Scale offline"}
            </span>
          )}
        </div>

        {errorCount > 0 && (
          <button
            type="button"
            onClick={retryAllFailed}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700/50 rounded-full px-3 py-1"
          >
            <RefreshCw className="w-3 h-3" />
            {errorCount} row(s) failed to save — Retry All
          </button>
        )}
      </div>

      {/* Column headers */}
      <div className="shrink-0 grid grid-cols-[3rem_1fr_1fr_1fr_1fr_2rem] gap-2 px-2 pb-1 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
        <div className="text-center">S.No</div>
        <div>Melt Number</div>
        <div>Weight</div>
        <div className="text-right">Weight (g)</div>
        <div className="text-right">Static Moment</div>
        <div />
      </div>

      {/* Grid body */}
      <div className="flex-1 overflow-y-auto px-1 space-y-0.5 pb-4">
        {rows.map((row, idx) => (
          <GridRow
            key={row.s_no}
            row={row}
            rowIndex={idx}
            focusedRowIndex={focusedRowIndex}
            focusedColumn={focusedColumn}
            nav={nav}
            onCellChange={handleCellChange}
            onFocusCell={focusCell}
            onRetrySave={(rowIndex) => void saveRow(rowIndex)}
            onScanClick={(rowIndex) => {
              focusCell(rowIndex, "melt_number");
              setCameraTargetRow(rowIndex);
            }}
            onKeyboardClick={(rowIndex) => {
              focusCell(rowIndex, "melt_number");
              setKeyboardTargetRow(rowIndex);
            }}
            onLockWeight={handleLockWeight}
            onUnlockWeight={handleUnlockWeight}
          />
        ))}
      </div>

      {/* Footer */}
      <div className="shrink-0 flex items-center justify-between gap-3 px-2 py-3 border-t border-slate-200 dark:border-slate-700/60">
        <p className="text-xs text-slate-400 dark:text-slate-500">
          {isEntryComplete ? (
            <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-medium">
              <Check className="w-3.5 h-3.5" /> Entry complete
            </span>
          ) : (
            "Rows auto-save as Melt Number and Weight are both entered."
          )}
        </p>
        <Button
          type="button"
          onClick={() => void handleComplete()}
          disabled={completing || isEntryComplete}
          className="bg-emerald-500 hover:bg-emerald-600 text-white px-8"
        >
          {completing ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Checking…
            </>
          ) : isEntryComplete ? (
            <>
              <Check className="w-4 h-4" />
              Completed
            </>
          ) : (
            "Save / Complete"
          )}
        </Button>
      </div>
    </div>
  );
}
