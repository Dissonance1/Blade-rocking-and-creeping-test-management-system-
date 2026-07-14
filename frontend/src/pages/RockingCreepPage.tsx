import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ExternalLink,
  Save,
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

  // ── DTI gauge — one physical button press = one captured value ─────────────
  const { lastReading, connected: dtiConnected } = useDTISocket(DTI_STATION);
  const lastAppliedAtRef = useRef<number>(0);

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

  const handleSave = useCallback(
    (entry: BladeRockingCreepEntry) => {
      const row = rowState[entry.blade_id];
      if (!row) return;
      const rocking = row.rocking !== "" ? parseFloat(row.rocking) : null;
      const creep   = row.creep   !== "" ? parseFloat(row.creep)   : null;
      const isLPTR  = entry.blade_type === "LPTR";

      if (isLPTR) {
        if (rocking === null) { toast.error("Rocking value is required for LPTR blades"); return; }
        if (creep   === null) { toast.error("Creep value is required for LPTR blades");   return; }
      } else {
        if (rocking === null) { toast.error("Rocking value is required for HPTR blades"); return; }
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

  // ── Next editable target after (entries[index], field) ──────────────────────
  const advanceTarget = useCallback(
    (fromEntry: BladeRockingCreepEntry, fromField: ActiveField) => {
      if (fromField === "rocking" && fromEntry.blade_type === "LPTR") {
        setActiveTarget({ bladeId: fromEntry.blade_id, field: "creep" });
        return;
      }
      const idx = entries.findIndex((e) => e.blade_id === fromEntry.blade_id);
      const next = entries.slice(idx + 1).find((e) => !!e.slot_number && !isEntryComplete(e));
      setActiveTarget(next ? { bladeId: next.blade_id, field: "rocking" } : null);
    },
    [entries, isEntryComplete]
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
  // NOTE: the backend requires rocking_value AND creep_value together in one
  // PATCH for LPTR blades (rejects a rocking-only save with 422) — so for LPTR
  // we buffer the Rocking capture locally and only save once Creep arrives too,
  // matching the same completeness rule the manual Save button already enforces.
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

    const isLPTR = entry.blade_type === "LPTR";
    const rockingNum = updatedRow.rocking !== "" ? parseFloat(updatedRow.rocking) : null;
    const creepNum   = updatedRow.creep   !== "" ? parseFloat(updatedRow.creep)   : null;
    const readyToSave = isLPTR ? rockingNum !== null && creepNum !== null : rockingNum !== null;

    if (readyToSave) {
      saveMutation.mutate({ bladeId, rocking: rockingNum, creep: creepNum });
    }
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

  // Save a row only once it actually has everything its blade type needs —
  // never toasts, since manual column-fill entry deliberately leaves LPTR
  // rows half-filled (Rocking only) until a second pass fills Creep.
  const trySaveIfReady = useCallback(
    (entry: BladeRockingCreepEntry) => {
      const row = rowState[entry.blade_id];
      if (!row) return;
      const rocking = row.rocking !== "" ? parseFloat(row.rocking) : null;
      const creep = row.creep !== "" ? parseFloat(row.creep) : null;
      const ready = entry.blade_type === "LPTR" ? rocking !== null && creep !== null : rocking !== null;
      if (ready) saveMutation.mutate({ bladeId: entry.blade_id, rocking, creep });
    },
    [rowState, saveMutation]
  );

  // ── Enter-to-confirm for manual typing: stays in the SAME column, next
  //    row — operators fill one whole column (Rocking, then Creep) down the
  //    grid rather than row-by-row. HPTR has no Creep column, so a Creep
  //    Enter only ever lands on the next LPTR row. ─────────────────────────
  const handleFieldEnter = useCallback(
    (entry: BladeRockingCreepEntry, field: ActiveField) => {
      const row = rowState[entry.blade_id] ?? EMPTY_ROW;
      const value = field === "rocking" ? row.rocking : row.creep;
      if (value.trim() === "") return;

      trySaveIfReady(entry);

      const idx = entries.findIndex((e) => e.blade_id === entry.blade_id);
      const next = entries
        .slice(idx + 1)
        .find((e) => !!e.slot_number && (field === "rocking" || e.blade_type === "LPTR"));
      setActiveTarget(next ? { bladeId: next.blade_id, field } : null);
    },
    [rowState, entries, trySaveIfReady]
  );

  // ── Stats derived from entries ───────────────────────────────────────────────
  const totalCount     = entries.length;
  const slottedCount   = entries.filter((e) => !!e.slot_number).length;
  const completedCount = entries.filter(
    (e) => e.rocking_value != null || (rowState[e.blade_id]?.saved ?? false)
  ).length;
  const activeEntry = activeTarget ? entries.find((e) => e.blade_id === activeTarget.bladeId) : undefined;

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
          <CardHeader className="pb-0 pt-4 px-4 border-b border-slate-100 dark:border-slate-700/50">
            <CardTitle className="text-base text-slate-900 dark:text-white flex items-center gap-2">
              Work Order {selectedBatch}
              {isFetching && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead className="bg-slate-800 dark:bg-background">
                  <tr>
                    {[
                      "Serial Number",
                      "Melt Number",
                      "Blade Type",
                      "Status",
                      "Slot No.",
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

                        {/* Blade type */}
                        <td className="px-4 py-3">
                          <span
                            className={cn(
                              "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
                              isLPTR
                                ? "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300"
                                : "bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300"
                            )}
                          >
                            {entry.blade_type}
                          </span>
                        </td>

                        {/* Status */}
                        <td className="px-4 py-3">
                          <StatusBadge status={entry.status} />
                        </td>

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
                              onChange={(e) =>
                                setRowState((prev) =>
                                  patchRow(prev, entry.blade_id, { rocking: e.target.value, saved: false })
                                )
                              }
                              onFocus={() => setActiveTarget({ bladeId: entry.blade_id, field: "rocking" })}
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
                              onChange={(e) =>
                                setRowState((prev) =>
                                  patchRow(prev, entry.blade_id, { creep: e.target.value, saved: false })
                                )
                              }
                              onFocus={() => setActiveTarget({ bladeId: entry.blade_id, field: "creep" })}
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

                        {/* Save */}
                        <td className="px-4 py-3">
                          {!entry.slot_number ? (
                            <span className="text-xs text-slate-400 dark:text-slate-500 italic">
                              Awaiting slot
                            </span>
                          ) : row.saved || (hasSavedData && !isSaving) ? (
                            <div className="flex items-center gap-2">
                              <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 text-xs font-medium">
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                Saved
                              </span>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleSave(entry)}
                                disabled={isSaving}
                                className="h-7 px-2 text-xs text-slate-500 hover:text-slate-800 dark:hover:text-white"
                              >
                                Update
                              </Button>
                            </div>
                          ) : (
                            <Button
                              size="sm"
                              onClick={() => handleSave(entry)}
                              disabled={isSaving}
                              className="bg-orange-500 hover:bg-orange-600 text-white h-8 px-3 text-xs"
                            >
                              {isSaving ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Save className="w-3.5 h-3.5" />
                              )}
                              Save
                            </Button>
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
