import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ExternalLink,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  FlaskConical,
  Package,
  Wifi,
  WifiOff,
  Crosshair,
} from "lucide-react";
import { RockingCreepIcon } from "@/components/common/CustomIcons";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { batchService, type BladeRockingCreepEntry } from "@/services/batchService";
import { bladeService } from "@/services/bladeService";
import { useDTISocket } from "@/hooks/useDTISocket";
import { cn } from "@/utils/cn";

// Only one DTI gauge is connected for Rocking & Creep entry — a fixed station id.
const DTI_STATION = "1";

type ActiveField = "rocking" | "creep";
interface ActiveTarget {
  bladeId: string;
  field: ActiveField;
}

// ─── Status badge ──────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  SENT_TO_ASSEMBLY: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300",
  SLOT_ASSIGNED:    "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  BALANCING_IN_PROGRESS: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  BALANCING_COMPLETED:   "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
  RETURNED_TO_OH:        "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  FINAL_VERIFICATION:    "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300",
  COMPLETED:             "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "bg-slate-100 text-slate-600 dark:bg-background dark:text-slate-300";
  const label = status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium", cls)}>
      {label}
    </span>
  );
}

// ─── Row state ────────────────────────────────────────────────────────────────

interface RowState {
  rocking: string;
  creep: string;
  saved: boolean;
}

const EMPTY_ROW: RowState = { rocking: "", creep: "", saved: false };

function patchRow(
  prev: Record<string, RowState>,
  id: string,
  patch: Partial<RowState>
): Record<string, RowState> {
  const base: RowState = prev[id] ?? EMPTY_ROW;
  return { ...prev, [id]: { ...base, ...patch } };
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function RockingCreepPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedBatch, setSelectedBatch] = useState("");
  const [rowState, setRowState] = useState<Record<string, RowState>>({});
  const [activeTarget, setActiveTarget] = useState<ActiveTarget | null>(null);

  // ── DTI gauge — one physical button press = one captured value. Must skip
  //    replay: this flow treats any "dti" message as a fresh press, so a
  //    reconnect (refresh, wifi blip, backend restart) replaying old Redis-
  //    buffered readings would silently auto-fill/save stale values. ────────
  const { lastReading, connected: dtiConnected } = useDTISocket(DTI_STATION, { replay: false });
  const lastAppliedAtRef = useRef<number>(0);

  // ── Debounced auto-save while typing — onBlur/Enter alone left a gap: a
  //    value typed and never blurred (e.g. the operator hits refresh right
  //    after typing) was never sent to the server and silently vanished.
  //    This fires shortly after typing pauses, independent of focus. ────────
  const AUTO_SAVE_DEBOUNCE_MS = 700;
  const autoSaveTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const clearAutoSaveTimer = useCallback((bladeId: string) => {
    const existing = autoSaveTimersRef.current.get(bladeId);
    if (existing) {
      clearTimeout(existing);
      autoSaveTimersRef.current.delete(bladeId);
    }
  }, []);

  // ── Input DOM refs, keyed "bladeId:field" — lets us move real keyboard
  //    focus (not just the visual highlight) when activeTarget advances ──────
  const inputRefs = useRef<Map<string, HTMLInputElement>>(new Map());
  const registerInputRef = useCallback(
    (bladeId: string, field: ActiveField, el: HTMLInputElement | null) => {
      const key = `${bladeId}:${field}`;
      if (el) inputRefs.current.set(key, el);
      else inputRefs.current.delete(key);
    },
    []
  );

  // ── Only work orders where Assembly has assigned at least one slot ──────────
  const { data: batches = [] } = useQuery({
    queryKey: ["batches", "with-slots"],
    queryFn: () => batchService.list({ has_slot_allocations: true }),
    staleTime: 30_000,
  });

  // ── Blades for selected work order with slot + rocking/creep data ───────────
  const {
    data: entries = [],
    isLoading,
    isFetching,
  } = useQuery({
    queryKey: ["rocking-creep", selectedBatch],
    queryFn: () => batchService.getRockingCreep(selectedBatch),
    enabled: !!selectedBatch,
    staleTime: 0,
  });

  // Initialise row inputs when data loads
  useEffect(() => {
    if (!entries.length) return;
    const init: Record<string, RowState> = {};
    entries.forEach((e) => {
      // Only reset rows not already dirty (don't overwrite user edits on refetch)
      if (!rowState[e.blade_id]) {
        init[e.blade_id] = {
          rocking: e.rocking_value != null ? String(e.rocking_value) : "",
          creep:   e.creep_value   != null ? String(e.creep_value)   : "",
          saved:   e.rocking_value != null || e.creep_value != null,
        };
      }
    });
    if (Object.keys(init).length) {
      setRowState((prev) => ({ ...init, ...prev }));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries]);

  // ── Save mutation (per row) ──────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: ({
      bladeId,
      rocking,
      creep,
    }: {
      bladeId: string;
      rocking: number | null;
      creep: number | null;
    }) => {
      const payload: { rocking_value?: number | null; creep_value?: number | null } = {};
      if (rocking !== null) payload.rocking_value = rocking;
      if (creep   !== null) payload.creep_value   = creep;
      return bladeService.setRockingCreep(bladeId, payload);
    },
    onSuccess: (_, vars) => {
      toast.success("Saved");
      setRowState((prev) => patchRow(prev, vars.bladeId, { saved: true }));
      queryClient.invalidateQueries({ queryKey: ["rocking-creep", selectedBatch] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to save");
    },
  });

  // Rocking and Creep are saved independently — the gauge is shared between
  // two separate measurement fixtures, so whichever value the operator has
  // just entered is saved on its own; the other one may already exist, may
  // follow later, or may never have been asked for (HPTR has no Creep).
  const handleSave = useCallback(
    (entry: BladeRockingCreepEntry) => {
      const row = rowState[entry.blade_id];
      if (!row) return;
      const rocking = row.rocking !== "" ? parseFloat(row.rocking) : null;
      const creep   = row.creep   !== "" ? parseFloat(row.creep)   : null;

      if (rocking === null && creep === null) {
        toast.error("Enter a Rocking or Creep value first");
        return;
      }
      saveMutation.mutate({ bladeId: entry.blade_id, rocking, creep });
    },
    [rowState, saveMutation]
  );

  // An entry is "done" once it has every value its blade type requires,
  // per server-confirmed data — NOT client-only rowState, so this stays
  // correct across refetches (e.g. after a save invalidates the query).
  const isEntryComplete = useCallback((e: BladeRockingCreepEntry) => {
    if (e.rocking_value == null) return false;
    return e.blade_type === "LPTR" ? e.creep_value != null : true;
  }, []);

  // Whether a specific column already has a server-confirmed value for this
  // blade — HPTR has no Creep column at all, so it's treated as pre-filled.
  const isFieldFilled = useCallback((e: BladeRockingCreepEntry, field: ActiveField) => {
    if (field === "creep" && e.blade_type !== "LPTR") return true;
    return (field === "rocking" ? e.rocking_value : e.creep_value) != null;
  }, []);

  // ── Next editable target after (entries[index], field) ──────────────────────
  // Stays in the SAME column — the gauge physically sits at one measurement
  // fixture (Rocking or Creep) for a batch of blades before moving to the
  // other, so the next suggested cell is the next row still missing THIS
  // column, not a jump to the other column on the same row.
  const advanceTarget = useCallback(
    (fromEntry: BladeRockingCreepEntry, fromField: ActiveField) => {
      const idx = entries.findIndex((e) => e.blade_id === fromEntry.blade_id);
      const next = entries.slice(idx + 1).find((e) => !!e.slot_number && !isFieldFilled(e, fromField));
      setActiveTarget(next ? { bladeId: next.blade_id, field: fromField } : null);
    },
    [entries, isFieldFilled]
  );

  // Default the active target to the first editable, not-yet-complete blade
  // once a work order's data loads (or a save refetches it) — but never
  // override an operator's own click, and never re-target an already-complete
  // row (otherwise finishing the last blade would loop the cursor back to
  // row 1 on the post-save refetch, risking an accidental overwrite there).
  useEffect(() => {
    if (activeTarget || !entries.length) return;
    const first = entries.find((e) => !!e.slot_number && !isEntryComplete(e));
    if (first) setActiveTarget({ bladeId: first.blade_id, field: "rocking" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries]);

  // ── Apply each new DTI gauge reading to whichever cell is active ────────────
  // The gauge is shared between the Rocking and Creep fixtures, so each
  // capture is saved on its own the moment it arrives — it never waits for
  // the other column, which may be filled already, later, or never (HPTR).
  useEffect(() => {
    if (!lastReading || !activeTarget) return;
    const capturedAt = lastReading.capturedAt.getTime();
    if (capturedAt === lastAppliedAtRef.current) return; // already applied this reading
    lastAppliedAtRef.current = capturedAt;

    const entry = entries.find((e) => e.blade_id === activeTarget.bladeId);
    if (!entry || !entry.slot_number) return; // target no longer editable — ignore

    const value = Number(lastReading.value.toFixed(4));
    const { bladeId, field } = activeTarget;
    const existingRow = rowState[bladeId] ?? EMPTY_ROW;
    const updatedRow: RowState = { ...existingRow, [field]: String(value), saved: false };
    setRowState((prev) => patchRow(prev, bladeId, { [field]: String(value), saved: false }));

    const rockingNum = updatedRow.rocking !== "" ? parseFloat(updatedRow.rocking) : null;
    const creepNum   = updatedRow.creep   !== "" ? parseFloat(updatedRow.creep)   : null;
    saveMutation.mutate({ bladeId, rocking: rockingNum, creep: creepNum });
    advanceTarget(entry, field);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastReading]);

  // ── Move real keyboard focus whenever the active target advances (DTI
  //    capture or Enter-to-confirm below) — activeTarget only drove the
  //    visual highlight before, the cursor never actually followed it ───────
  useEffect(() => {
    if (!activeTarget) return;
    const el = inputRefs.current.get(`${activeTarget.bladeId}:${activeTarget.field}`);
    el?.focus();
    el?.select?.();
  }, [activeTarget]);

  // Save whichever column(s) are filled in — never toasts, since manual
  // column-fill entry deliberately leaves LPTR rows half-filled (Rocking
  // only, or Creep only) until a later pass fills the other column.
  const trySaveIfReady = useCallback(
    (entry: BladeRockingCreepEntry) => {
      const row = rowState[entry.blade_id];
      if (!row) return;
      const rocking = row.rocking !== "" ? parseFloat(row.rocking) : null;
      const creep = row.creep !== "" ? parseFloat(row.creep) : null;
      if (rocking !== null || creep !== null) {
        saveMutation.mutate({ bladeId: entry.blade_id, rocking, creep });
      }
    },
    [rowState, saveMutation]
  );

  // Debounced counterpart to trySaveIfReady — called from onChange so typing
  // gets persisted a moment after the operator stops, without waiting for
  // blur/Enter. Restarts the timer on every keystroke for that blade.
  const scheduleAutoSave = useCallback(
    (entry: BladeRockingCreepEntry) => {
      clearAutoSaveTimer(entry.blade_id);
      const timer = setTimeout(() => {
        autoSaveTimersRef.current.delete(entry.blade_id);
        trySaveIfReady(entry);
      }, AUTO_SAVE_DEBOUNCE_MS);
      autoSaveTimersRef.current.set(entry.blade_id, timer);
    },
    [clearAutoSaveTimer, trySaveIfReady]
  );

  // Flush all pending debounced saves immediately — used when navigating
  // away (work order switch / unmount) so a typed-but-not-yet-debounced
  // value isn't lost to the same gap this whole mechanism exists to close.
  const flushAutoSaves = useCallback(() => {
    for (const [bladeId, timer] of autoSaveTimersRef.current) {
      clearTimeout(timer);
      autoSaveTimersRef.current.delete(bladeId);
      const entry = entries.find((e) => e.blade_id === bladeId);
      if (entry) trySaveIfReady(entry);
    }
  }, [entries, trySaveIfReady]);

  // Flush on unmount (e.g. navigating to a different page) too — kept in a
  // ref so the cleanup always calls the latest closure without re-running
  // this effect (and re-arming the cleanup) on every render.
  const flushAutoSavesRef = useRef(flushAutoSaves);
  useEffect(() => {
    flushAutoSavesRef.current = flushAutoSaves;
  }, [flushAutoSaves]);
  useEffect(() => {
    return () => flushAutoSavesRef.current();
  }, []);

  // ── Enter-to-confirm for manual typing: stays in the SAME column, next
  //    row — operators fill one whole column (Rocking, then Creep) down the
  //    grid rather than row-by-row. HPTR has no Creep column, so a Creep
  //    Enter only ever lands on the next LPTR row. ─────────────────────────
  const handleFieldEnter = useCallback(
    (entry: BladeRockingCreepEntry, field: ActiveField) => {
      const row = rowState[entry.blade_id] ?? EMPTY_ROW;
      const value = field === "rocking" ? row.rocking : row.creep;
      if (value.trim() === "") return;

      clearAutoSaveTimer(entry.blade_id);
      trySaveIfReady(entry);

      const idx = entries.findIndex((e) => e.blade_id === entry.blade_id);
      const next = entries
        .slice(idx + 1)
        .find((e) => !!e.slot_number && (field === "rocking" || e.blade_type === "LPTR"));
      setActiveTarget(next ? { bladeId: next.blade_id, field } : null);
    },
    [rowState, entries, trySaveIfReady, clearAutoSaveTimer]
  );

  // ── Stats derived from entries ───────────────────────────────────────────────
  const totalCount     = entries.length;
  const slottedCount   = entries.filter((e) => !!e.slot_number).length;
  const completedCount = entries.filter(
    (e) => e.rocking_value != null || (rowState[e.blade_id]?.saved ?? false)
  ).length;
  const activeEntry = activeTarget ? entries.find((e) => e.blade_id === activeTarget.bladeId) : undefined;

  // Blade type + status breakdown for the header — a work order mixes LPTR
  // and HPTR blades, and status can differ row to row, so there is no single
  // "the" type/status to show; a per-value count summary is the honest one.
  const lptrCount = entries.filter((e) => e.blade_type === "LPTR").length;
  const hptrCount = entries.filter((e) => e.blade_type === "HPTR").length;
  const statusCounts = entries.reduce<Record<string, number>>((acc, e) => {
    acc[e.status] = (acc[e.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Page header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <RockingCreepIcon className="w-5 h-5 text-orange-500 shrink-0" />
              Rocking &amp; Creep Entry
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight mt-0.5">
              Enter Rocking and Creep values for blades after Assembly slot allocation
            </p>
          </div>
        </div>
      </div>

      <div className="w-full px-4 sm:px-6 py-6 sm:py-8 space-y-6">

      {/* Work order selector + stats bar */}
      <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60">
        <CardContent className="pt-4 pb-4">
          <div className="flex flex-wrap items-center gap-4">
            {/* Work order selector */}
            <div className="flex items-center gap-2 flex-1 min-w-[220px] max-w-xs">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap">
                Select Work Order
              </label>
              <div className="relative flex-1">
                <select
                  value={selectedBatch}
                  onChange={(e) => {
                    flushAutoSaves();
                    setSelectedBatch(e.target.value);
                    setRowState({});
                    setActiveTarget(null);
                  }}
                  className="w-full appearance-none rounded-lg border border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-background text-slate-900 dark:text-white px-3 py-2 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                >
                  <option value="">— choose a work order —</option>
                  {batches.map((b) => (
                    <option key={b.work_order_number} value={b.work_order_number}>
                      {b.work_order_number}
                      {b.part_number ? ` · ${b.part_number}` : ""}
                      {` (${b.blade_count} blades)`}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              </div>
            </div>

            {/* Stats pills (only when a work order is loaded) */}
            {selectedBatch && !isLoading && (
              <div className="flex items-center gap-3 text-sm">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 dark:bg-background px-3 py-1 font-medium text-slate-700 dark:text-slate-300">
                  <Package className="w-3.5 h-3.5" />
                  {totalCount} blades
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 dark:bg-blue-900/20 px-3 py-1 font-medium text-blue-700 dark:text-blue-300">
                  {slottedCount} slotted
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 px-3 py-1 font-medium text-emerald-700 dark:text-emerald-300">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  {completedCount} / {totalCount} entered
                </span>
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-medium",
                    dtiConnected
                      ? "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300"
                      : "bg-slate-100 dark:bg-background text-slate-400"
                  )}
                >
                  {dtiConnected ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
                  DTI {dtiConnected ? "connected" : "offline"}
                </span>
                {activeEntry && (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-orange-50 dark:bg-orange-900/20 px-3 py-1 font-medium text-orange-600 dark:text-orange-400">
                    <Crosshair className="w-3.5 h-3.5" />
                    Next capture → {activeEntry.serial_number} ({activeTarget?.field === "creep" ? "Creep" : "Rocking"})
                  </span>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Empty — no work order selected */}
      {!selectedBatch && (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-slate-400 dark:text-slate-600">
          <FlaskConical className="w-16 h-16 opacity-30" />
          <p className="text-lg font-medium">Select a work order above to begin entry</p>
          <p className="text-sm text-center max-w-xs">
            Rocking and Creep values can be entered once Assembly has assigned slot numbers to the blades.
          </p>
        </div>
      )}

      {/* Loading */}
      {selectedBatch && isLoading && (
        <div className="flex items-center justify-center py-20 gap-3 text-slate-500 dark:text-slate-400">
          <Loader2 className="w-6 h-6 animate-spin" />
          Loading work order data…
        </div>
      )}

      {/* Table */}
      {selectedBatch && !isLoading && entries.length > 0 && (
        <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 overflow-hidden">
          <CardHeader className="pb-3 pt-4 px-4 border-b border-slate-100 dark:border-slate-700/50">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <CardTitle className="text-base text-slate-900 dark:text-white flex items-center gap-2">
                Work Order {selectedBatch}
                {isFetching && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />}
              </CardTitle>

              {/* Blade type breakdown */}
              <div className="flex items-center gap-1.5">
                {lptrCount > 0 && (
                  <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300">
                    {lptrCount} LPTR
                  </span>
                )}
                {hptrCount > 0 && (
                  <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                    {hptrCount} HPTR
                  </span>
                )}
              </div>

              {/* Status breakdown */}
              <div className="flex items-center gap-1.5">
                {Object.entries(statusCounts).map(([status, count]) => (
                  <span key={status} className="inline-flex items-center gap-1">
                    <StatusBadge status={status} />
                    <span className="text-[11px] text-slate-400 dark:text-slate-500">×{count}</span>
                  </span>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead className="bg-slate-800 dark:bg-background">
                  <tr>
                    {[
                      "Slot No.",
                      "Serial Number",
                      "Melt Number",
                      "Weight (g)",
                      "Static Moment",
                      "Rocking Value",
                      "Creep Value",
                      "Action",
                    ].map((h) => (
                      <th
                        key={h}
                        className="text-left px-4 py-3 text-slate-100 font-semibold text-xs uppercase tracking-wide whitespace-nowrap"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                  {entries.map((entry, rowIdx) => {
                    const row = rowState[entry.blade_id] ?? {
                      rocking: "",
                      creep: "",
                      saved: false,
                    };
                    const isSaving =
                      saveMutation.isPending &&
                      (saveMutation.variables as any)?.bladeId === entry.blade_id;
                    const hasSavedData = entry.rocking_value != null || entry.creep_value != null;
                    const isLPTR = entry.blade_type === "LPTR";

                    return (
                      <tr
                        key={entry.blade_id}
                        className={cn(
                          "transition-colors",
                          rowIdx % 2 === 0
                            ? "bg-white dark:bg-background"
                            : "bg-slate-50 dark:bg-background",
                          (row.saved || hasSavedData) && "border-l-2 border-l-emerald-400"
                        )}
                      >
                        {/* Slot */}
                        <td className="px-4 py-3">
                          {entry.slot_number ? (
                            <span className="inline-flex items-center justify-center w-9 h-9 rounded-lg bg-blue-600 text-white text-sm font-bold shadow-sm">
                              {entry.slot_number}
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-amber-500 dark:text-amber-400 text-xs font-medium">
                              <AlertTriangle className="w-3.5 h-3.5" />
                              Not assigned
                            </span>
                          )}
                        </td>

                        {/* Serial */}
                        <td className="px-4 py-3">
                          <button
                            onClick={() => navigate(`/blades/${entry.blade_id}`)}
                            className="font-mono font-medium text-orange-500 hover:text-orange-600 dark:text-orange-400 dark:hover:text-orange-300 flex items-center gap-1"
                          >
                            {entry.serial_number}
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </td>

                        {/* Melt */}
                        <td className="px-4 py-3 font-mono text-slate-700 dark:text-slate-300">
                          {entry.melt_number}
                        </td>

                        {/* Weight */}
                        <td className="px-4 py-3 font-mono text-slate-700 dark:text-slate-300">
                          {entry.weight_grams != null ? entry.weight_grams.toFixed(2) : (
                            <span className="text-slate-300 dark:text-slate-600">—</span>
                          )}
                        </td>

                        {/* Static moment */}
                        <td className="px-4 py-3 font-mono text-slate-700 dark:text-slate-300">
                          {entry.static_moment_gcm != null ? entry.static_moment_gcm.toFixed(2) : (
                            <span className="text-slate-300 dark:text-slate-600">—</span>
                          )}
                        </td>

                        {/* Rocking input */}
                        <td className="px-4 py-3">
                          {entry.slot_number ? (
                            <Input
                              ref={(el) => registerInputRef(entry.blade_id, "rocking", el)}
                              type="number"
                              step="0.0001"
                              min={0}
                              placeholder="0.0000"
                              value={row.rocking}
                              onChange={(e) => {
                                setRowState((prev) =>
                                  patchRow(prev, entry.blade_id, { rocking: e.target.value, saved: false })
                                );
                                scheduleAutoSave(entry);
                              }}
                              onFocus={() => setActiveTarget({ bladeId: entry.blade_id, field: "rocking" })}
                              onBlur={() => { clearAutoSaveTimer(entry.blade_id); trySaveIfReady(entry); }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  handleFieldEnter(entry, "rocking");
                                }
                              }}
                              className={cn(
                                "w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white font-mono text-sm h-8",
                                activeTarget?.bladeId === entry.blade_id &&
                                  activeTarget.field === "rocking" &&
                                  "ring-2 ring-orange-400 border-orange-400"
                              )}
                            />
                          ) : (
                            <span className="text-slate-300 dark:text-slate-600">—</span>
                          )}
                        </td>

                        {/* Creep input */}
                        <td className="px-4 py-3">
                          {!entry.slot_number ? (
                            <span className="text-slate-300 dark:text-slate-600">—</span>
                          ) : isLPTR ? (
                            <Input
                              ref={(el) => registerInputRef(entry.blade_id, "creep", el)}
                              type="number"
                              step="0.0001"
                              min={0}
                              placeholder="0.0000"
                              value={row.creep}
                              onChange={(e) => {
                                setRowState((prev) =>
                                  patchRow(prev, entry.blade_id, { creep: e.target.value, saved: false })
                                );
                                scheduleAutoSave(entry);
                              }}
                              onFocus={() => setActiveTarget({ bladeId: entry.blade_id, field: "creep" })}
                              onBlur={() => { clearAutoSaveTimer(entry.blade_id); trySaveIfReady(entry); }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  handleFieldEnter(entry, "creep");
                                }
                              }}
                              className={cn(
                                "w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white font-mono text-sm h-8",
                                activeTarget?.bladeId === entry.blade_id &&
                                  activeTarget.field === "creep" &&
                                  "ring-2 ring-orange-400 border-orange-400"
                              )}
                            />
                          ) : (
                            <span className="text-xs text-slate-400 dark:text-slate-500 italic">
                              N/A (HPTR)
                            </span>
                          )}
                        </td>

                        {/* Save status — entry auto-saves (DTI capture, or Enter/blur while
                            typing), so there's nothing to click the first time. "Update" only
                            appears once a value exists, for manually re-pushing a correction. */}
                        <td className="px-4 py-3">
                          {!entry.slot_number ? (
                            <span className="text-xs text-slate-400 dark:text-slate-500 italic">
                              Awaiting slot
                            </span>
                          ) : isSaving ? (
                            <span className="flex items-center gap-1 text-slate-500 dark:text-slate-400 text-xs font-medium">
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              Saving…
                            </span>
                          ) : row.saved || hasSavedData ? (
                            <div className="flex items-center gap-2">
                              <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 text-xs font-medium">
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                Saved
                              </span>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleSave(entry)}
                                className="h-7 px-2 text-xs text-slate-500 hover:text-slate-800 dark:hover:text-white"
                              >
                                Update
                              </Button>
                            </div>
                          ) : (
                            <span className="text-xs text-slate-400 dark:text-slate-500 italic">
                              Auto-saves on entry
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty work order — no blades */}
      {selectedBatch && !isLoading && entries.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 gap-3 text-slate-400 dark:text-slate-600">
          <Package className="w-12 h-12 opacity-30" />
          <p className="font-medium">No blades found in work order {selectedBatch}</p>
        </div>
      )}

    </div>
  </div>
);
}
