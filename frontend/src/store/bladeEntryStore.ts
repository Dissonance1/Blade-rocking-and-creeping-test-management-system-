import { create } from "zustand";
import type { BladeType, WorkOrderDetail } from "@/services/workOrderService";

export const BLADES_PER_WORK_ORDER = 90;
const WEIGHT_TO_GRAMS_FACTOR = 1.57;
const STATIC_MOMENT_FACTOR = 20;

export type RowSaveStatus = "empty" | "dirty" | "saving" | "saved" | "error";
export type GridColumn = "melt_number" | "weight";

export interface GridRowState {
  s_no: number;
  blade_id: string | null;
  melt_number: string;
  ocr_melt_number: string;
  ocr_mismatch_flag: boolean;
  raw_weight: string; // kept as string to preserve user typing / avoid float jitter
  weight_grams: number | null;
  static_moment_gcm: number | null;
  status: RowSaveStatus;
  locked: boolean;
  error_message: string | null;
}

export interface CommonInfo {
  work_order_number: string;
  shop_order_number: string;
  part_number: string;
  blade_type: BladeType;
  engine_number: string;
  engine_hours: string;
  component_hours: string;
}

export type EntryPhase = "loading" | "common-info" | "grid";

interface CompleteError {
  message: string;
  incomplete_rows?: number[];
  duplicate_groups?: { melt_number: string; s_nos: number[] }[];
}

function emptyRow(sNo: number): GridRowState {
  return {
    s_no: sNo,
    blade_id: null,
    melt_number: "",
    ocr_melt_number: "",
    ocr_mismatch_flag: false,
    raw_weight: "",
    weight_grams: null,
    static_moment_gcm: null,
    status: "empty",
    locked: false,
    error_message: null,
  };
}

function computeDerived(rawWeight: string): { weight_grams: number | null; static_moment_gcm: number | null } {
  const n = parseFloat(rawWeight);
  if (isNaN(n) || n <= 0) return { weight_grams: null, static_moment_gcm: null };
  const wg = Math.round(n * WEIGHT_TO_GRAMS_FACTOR * 100) / 100;
  const sm = Math.round(wg * STATIC_MOMENT_FACTOR * 100) / 100;
  return { weight_grams: wg, static_moment_gcm: sm };
}

function isRowReadyToSave(row: GridRowState): boolean {
  return row.melt_number.trim().length > 0 && row.weight_grams != null;
}

interface BladeEntryState {
  phase: EntryPhase;
  commonInfo: CommonInfo;
  commonInfoLocked: boolean;
  rows: GridRowState[];
  focusedRowIndex: number;
  focusedColumn: GridColumn;
  isEntryComplete: boolean;
  completeDialogOpen: boolean;
  completeErrors: CompleteError | null;

  setPhase: (phase: EntryPhase) => void;
  setCommonInfoField: <K extends keyof CommonInfo>(field: K, value: CommonInfo[K]) => void;
  lockCommonInfo: () => void;
  initBlankGrid: () => void;
  loadFromServer: (detail: WorkOrderDetail) => void;
  applyServerRow: (row: import("@/services/workOrderService").WorkOrderRow) => void;
  setCellValue: (rowIndex: number, column: GridColumn, value: string) => boolean;
  lockRowWeight: (rowIndex: number) => void;
  unlockRow: (rowIndex: number) => void;
  markRowSaving: (rowIndex: number) => void;
  markRowSaved: (rowIndex: number) => void;
  markRowError: (rowIndex: number, message: string) => void;
  focusCell: (rowIndex: number, column: GridColumn) => void;
  firstIncompleteIndex: () => number | null;
  openCompleteDialog: (errors: CompleteError) => void;
  closeCompleteDialog: () => void;
  markEntryComplete: () => void;
  reset: () => void;
}

const initialCommonInfo: CommonInfo = {
  work_order_number: "",
  shop_order_number: "",
  part_number: "",
  blade_type: "LPTR",
  engine_number: "",
  engine_hours: "",
  component_hours: "",
};

export const useBladeEntryStore = create<BladeEntryState>((set, get) => ({
  phase: "common-info",
  commonInfo: { ...initialCommonInfo },
  commonInfoLocked: false,
  rows: [],
  focusedRowIndex: 0,
  focusedColumn: "melt_number",
  isEntryComplete: false,
  completeDialogOpen: false,
  completeErrors: null,

  setPhase: (phase) => set({ phase }),

  setCommonInfoField: (field, value) =>
    set((s) => ({ commonInfo: { ...s.commonInfo, [field]: value } })),

  lockCommonInfo: () => set({ commonInfoLocked: true }),

  initBlankGrid: () =>
    set({
      rows: Array.from({ length: BLADES_PER_WORK_ORDER }, (_, i) => emptyRow(i + 1)),
      phase: "grid",
      focusedRowIndex: 0,
      focusedColumn: "melt_number",
    }),

  loadFromServer: (detail) => {
    const rows: GridRowState[] = detail.rows.map((r) => {
      const raw = r.raw_weight != null ? String(r.raw_weight) : "";
      return {
        s_no: r.s_no,
        blade_id: r.blade_id,
        melt_number: r.melt_number ?? "",
        ocr_melt_number: r.ocr_melt_number ?? "",
        ocr_mismatch_flag: r.ocr_mismatch_flag,
        raw_weight: raw,
        weight_grams: r.weight_grams,
        static_moment_gcm: r.static_moment_gcm,
        status: r.is_complete ? "saved" : "empty",
        locked: r.is_complete,
        error_message: null,
      };
    });
    const firstIncomplete = detail.first_incomplete_s_no;
    const focusIndex = firstIncomplete != null ? firstIncomplete - 1 : Math.max(0, rows.length - 1);
    set({
      commonInfo: {
        work_order_number: detail.work_order_number,
        shop_order_number: detail.shop_order_number,
        part_number: detail.part_number,
        blade_type: detail.blade_type,
        engine_number: detail.engine_number ?? "",
        engine_hours: detail.engine_hours,
        component_hours: detail.component_hours ?? "",
      },
      commonInfoLocked: true,
      rows,
      phase: "grid",
      isEntryComplete: detail.is_entry_complete,
      focusedRowIndex: focusIndex,
      focusedColumn: "melt_number",
    });
  },

  applyServerRow: (row) => {
    set((s) => ({
      rows: s.rows.map((r) =>
        r.s_no === row.s_no
          ? {
              ...r,
              blade_id: row.blade_id,
              weight_grams: row.weight_grams,
              static_moment_gcm: row.static_moment_gcm,
            }
          : r
      ),
    }));
  },

  setCellValue: (rowIndex, column, value) => {
    let readyToSave = false;
    set((s) => {
      const existing = s.rows[rowIndex];
      if (!existing) return s;
      const rows = s.rows.slice();
      const row = { ...existing };
      if (row.locked) row.locked = false;
      if (column === "melt_number") {
        row.melt_number = value;
      } else {
        row.raw_weight = value;
        const derived = computeDerived(value);
        row.weight_grams = derived.weight_grams;
        row.static_moment_gcm = derived.static_moment_gcm;
      }
      row.status = isRowReadyToSave(row) ? "dirty" : "empty";
      readyToSave = row.status === "dirty";
      rows[rowIndex] = row;
      return { rows };
    });
    return readyToSave;
  },

  lockRowWeight: (rowIndex) =>
    set((s) => {
      const existing = s.rows[rowIndex];
      if (!existing) return s;
      const rows = s.rows.slice();
      rows[rowIndex] = { ...existing, locked: true };
      return { rows };
    }),

  unlockRow: (rowIndex) =>
    set((s) => {
      const existing = s.rows[rowIndex];
      if (!existing) return s;
      const rows = s.rows.slice();
      rows[rowIndex] = { ...existing, locked: false };
      return { rows };
    }),

  markRowSaving: (rowIndex) =>
    set((s) => {
      const existing = s.rows[rowIndex];
      if (!existing) return s;
      const rows = s.rows.slice();
      rows[rowIndex] = { ...existing, status: "saving", error_message: null };
      return { rows };
    }),

  markRowSaved: (rowIndex) =>
    set((s) => {
      const existing = s.rows[rowIndex];
      if (!existing) return s;
      const rows = s.rows.slice();
      rows[rowIndex] = { ...existing, status: "saved", error_message: null };
      return { rows };
    }),

  markRowError: (rowIndex, message) =>
    set((s) => {
      const existing = s.rows[rowIndex];
      if (!existing) return s;
      const rows = s.rows.slice();
      rows[rowIndex] = { ...existing, status: "error", error_message: message };
      return { rows };
    }),

  focusCell: (rowIndex, column) => {
    const len = get().rows.length;
    const clamped = Math.max(0, Math.min(len - 1, rowIndex));
    set({ focusedRowIndex: clamped, focusedColumn: column });
  },

  firstIncompleteIndex: () => {
    const rows = get().rows;
    const idx = rows.findIndex((r) => r.status !== "saved");
    return idx === -1 ? null : idx;
  },

  openCompleteDialog: (errors) => set({ completeDialogOpen: true, completeErrors: errors }),
  closeCompleteDialog: () => set({ completeDialogOpen: false, completeErrors: null }),
  markEntryComplete: () => set({ isEntryComplete: true, completeDialogOpen: false, completeErrors: null }),

  reset: () =>
    set({
      phase: "common-info",
      commonInfo: { ...initialCommonInfo },
      commonInfoLocked: false,
      rows: [],
      focusedRowIndex: 0,
      focusedColumn: "melt_number",
      isEntryComplete: false,
      completeDialogOpen: false,
      completeErrors: null,
    }),
}));
