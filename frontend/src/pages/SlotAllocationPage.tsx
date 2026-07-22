import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  RefreshCw, PackageSearch, Play, Save, FileSpreadsheet, Scale, ClipboardCheck, Send,
} from "lucide-react";
import { toast } from "sonner";
import { SlotAllocationIcon } from "@/components/common/CustomIcons";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

import { bladeService } from "@/services/bladeService";
import { batchService, type LptrSlotAssignment } from "@/services/batchService";
import { slotService } from "@/services/slotService";
import { lptrService } from "@/services/lptrService";
import { reportService } from "@/services/reportService";
import type { BladeListItem, SlotAllocation } from "@/types";
import { cn } from "@/utils/cn";
import {
  LPTR_TOTAL_SLOTS, LPTR_STAGE1_COUNT, LPTR_STAGE2_COUNT,
  computeLptrStage1, computeLptrStage2,
  type LptrAllocationEntry, type LptrStage1Result,
} from "@/utils/lptrBalancing";

const ELIGIBLE_FOR_SLOT_STATUSES = new Set(["SENT_TO_ASSEMBLY", "ASSEMBLY_RECEIVED", "ASSEMBLY_VERIFIED"]);

// ─── Shared: W1/W2 half-split allocation tables ─────────────────────────────

const HALF_TABLE_HEADERS = ["Slot", "Blade Serial", "Melt No.", "Weight (g)", "Static Moment (g·cm)"];

function splitByHalf<T>(items: T[], slotOf: (item: T) => number, totalSlots: number = LPTR_TOTAL_SLOTS) {
  const half = totalSlots / 2;
  const w1 = items.filter((item) => slotOf(item) <= half).sort((a, b) => slotOf(a) - slotOf(b));
  const w2 = items.filter((item) => slotOf(item) > half).sort((a, b) => slotOf(a) - slotOf(b));
  return { half, w1, w2 };
}

function HalfTable({
  title,
  rows,
}: {
  title: string;
  rows: { slot: number; serial: string; melt: string | null | undefined; weight: number | null | undefined; staticMoment: number | null | undefined }[];
}) {
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between px-3 py-2 bg-slate-100 dark:bg-background rounded-t-lg border border-b-0 border-slate-200 dark:border-slate-700/60">
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</span>
        <span className="text-xs font-mono tabular-nums text-slate-500 dark:text-slate-400">{rows.length} slots</span>
      </div>
      <div className="border border-slate-200 dark:border-slate-700/60 rounded-b-lg overflow-x-auto max-h-[28rem] overflow-y-auto">
        <table className="w-full text-sm whitespace-nowrap">
          <thead className="sticky top-0">
            <tr className="bg-slate-800 dark:bg-background">
              {HALF_TABLE_HEADERS.map((hd) => (
                <th key={hd} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-100 whitespace-nowrap">
                  {hd}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
            {rows.map((r, idx) => (
              <tr key={`${r.slot}-${r.serial}`} className={cn(
                "transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/30",
                idx % 2 === 0 ? "bg-white dark:bg-background" : "bg-slate-50/60 dark:bg-background"
              )}>
                <td className="px-3 py-2.5 font-mono font-bold text-cyan-600 dark:text-cyan-400 text-sm">#{r.slot}</td>
                <td className="px-3 py-2.5 font-mono text-orange-500 dark:text-orange-400 text-xs font-semibold">{r.serial}</td>
                <td className="px-3 py-2.5 text-slate-600 dark:text-slate-300 text-xs">{r.melt ?? "—"}</td>
                <td className="px-3 py-2.5 tabular-nums text-slate-700 dark:text-slate-200 text-xs">
                  {r.weight != null ? Number(r.weight).toFixed(1) : "—"}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-slate-700 dark:text-slate-200 text-xs">
                  {r.staticMoment != null ? Number(r.staticMoment).toFixed(2) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AllocationTable({ entries }: { entries: LptrAllocationEntry[] }) {
  const { half, w1, w2 } = splitByHalf(entries, (e) => e.slot);
  const toRow = (e: LptrAllocationEntry) => ({
    slot: e.slot,
    serial: e.blade.serial_number,
    melt: e.blade.melt_number,
    weight: e.blade.weight_grams,
    staticMoment: e.blade.static_moment_gcm,
  });
  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <HalfTable title={`W1 — Slots 1–${half}`} rows={w1.map(toRow)} />
      <HalfTable title={`W2 — Slots ${half + 1}–${half * 2}`} rows={w2.map(toRow)} />
    </div>
  );
}

interface SavedRow { slot: SlotAllocation; blade: BladeListItem | undefined; }

function SavedSlotsTable({ rows }: { rows: SavedRow[] }) {
  const { half, w1, w2 } = splitByHalf(rows, (r) => parseInt(r.slot.slot_number, 10) || 0);
  const toRow = (r: SavedRow) => ({
    slot: parseInt(r.slot.slot_number, 10) || 0,
    serial: r.blade?.serial_number ?? "—",
    melt: r.blade?.melt_number,
    weight: r.blade?.weight_grams,
    staticMoment: r.blade?.static_moment_gcm,
  });
  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <HalfTable title={`W1 — Slots 1–${half}`} rows={w1.map(toRow)} />
      <HalfTable title={`W2 — Slots ${half + 1}–${half * 2}`} rows={w2.map(toRow)} />
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function SlotAllocationPage() {
  const qc = useQueryClient();
  const [selectedBatch, setSelectedBatch] = useState("");
  const [activeTab, setActiveTab] = useState("empty-rotor");

  const [unbalanceSlotInput, setUnbalanceSlotInput] = useState("");
  const [unbalanceValueInput, setUnbalanceValueInput] = useState("");

  const [stage1Preview, setStage1Preview] = useState<LptrStage1Result | null>(null);
  const [stage2Preview, setStage2Preview] = useState<LptrAllocationEntry[] | null>(null);

  const { data: batches = [] } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    staleTime: 30_000,
  });
  const eligibleBatches = useMemo(
    () => batches.filter((b) => ["ACCEPTED", "MODIFIED", "SLOTS_ALLOCATED", "BALANCED"].includes(b.current_status)),
    [batches]
  );
  // LPTR batches that already have at least one stage of slots saved but
  // haven't been through "Physical balancing confirmed?" yet — i.e. someone
  // needs to come back (maybe hours or a day later, once the physical
  // balancing test is done) and save that confirmation.
  const pendingBalancingBatches = useMemo(
    () => batches.filter((b) => b.blade_type === "LPTR" && b.current_status === "SLOTS_ALLOCATED"),
    [batches]
  );
  // LPTR batches marked balanced but not yet formally sent back to OH — a
  // deliberate separate step, since the blades may not physically travel
  // back to OH the moment balancing is confirmed.
  const pendingSendBackBatches = useMemo(
    () => batches.filter((b) => b.blade_type === "LPTR" && b.current_status === "BALANCED"),
    [batches]
  );
  const selectedBatchInfo = useMemo(
    () => batches.find((b) => b.work_order_number === selectedBatch),
    [batches, selectedBatch]
  );
  const isBalanced = selectedBatchInfo?.current_status === "BALANCED";

  const { data: bladesData, isLoading: bladesLoading } = useQuery({
    queryKey: ["blades", "lptr-batch", selectedBatch],
    queryFn: () => bladeService.list({ work_order_number: selectedBatch, blade_type: "LPTR", limit: 200 }),
    enabled: !!selectedBatch,
    staleTime: 0,
  });
  const blades: BladeListItem[] = bladesData?.items ?? [];
  const bladeMap = useMemo(() => {
    const m = new Map<string, BladeListItem>();
    blades.forEach((b) => m.set(b.id, b));
    return m;
  }, [blades]);

  const { data: batchSlotsRaw = [], isLoading: slotsLoading } = useQuery({
    queryKey: ["slots", selectedBatch],
    queryFn: () => slotService.list({ work_order_number: selectedBatch, limit: 200 }),
    enabled: !!selectedBatch,
    refetchInterval: 30_000,
  });
  const bladeIds = useMemo(() => new Set(blades.map((b) => b.id)), [blades]);
  const lptrSlots = useMemo(() => batchSlotsRaw.filter((s) => s.is_active && bladeIds.has(s.blade_id)), [batchSlotsRaw, bladeIds]);
  const stage1Slots = useMemo(() => lptrSlots.filter((s) => s.stage === 1), [lptrSlots]);
  const stage2Slots = useMemo(() => lptrSlots.filter((s) => s.stage === 2), [lptrSlots]);

  const { data: emptyRotor, isLoading: emptyRotorLoading } = useQuery({
    queryKey: ["lptr-empty-rotor", selectedBatch],
    queryFn: () => lptrService.getEmptyRotorReading(selectedBatch),
    enabled: !!selectedBatch,
  });

  const eligibleBlades = useMemo(
    () => blades.filter((b) => ELIGIBLE_FOR_SLOT_STATUSES.has(b.status)),
    [blades]
  );

  const unbalanceSlot = emptyRotor?.unbalance_slot;
  const unbalanceValue = emptyRotor ? Number(emptyRotor.unbalance_value) : undefined;

  function refresh() {
    qc.invalidateQueries({ queryKey: ["slots", selectedBatch] });
    qc.invalidateQueries({ queryKey: ["blades", "lptr-batch", selectedBatch] });
    qc.invalidateQueries({ queryKey: ["batches"] });
  }

  // ── Empty rotor ──────────────────────────────────────────────────────────
  const saveEmptyRotorMutation = useMutation({
    mutationFn: () => lptrService.saveEmptyRotorReading(selectedBatch, Number(unbalanceSlotInput), Number(unbalanceValueInput)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lptr-empty-rotor", selectedBatch] });
      toast.success("Empty rotor reading saved");
      setActiveTab("stage1");
    },
    onError: () => toast.error("Failed to save empty rotor reading"),
  });

  // ── Stage 1 ──────────────────────────────────────────────────────────────
  function handleRunStage1() {
    if (!unbalanceSlot || unbalanceValue == null) {
      toast.error("Record the empty rotor reading first");
      return;
    }
    if (eligibleBlades.length < LPTR_STAGE1_COUNT) {
      toast.error(`Need at least ${LPTR_STAGE1_COUNT} eligible blades, found ${eligibleBlades.length}`);
      return;
    }
    setStage1Preview(computeLptrStage1(eligibleBlades, unbalanceSlot, unbalanceValue, LPTR_TOTAL_SLOTS));
  }

  const saveStage1Mutation = useMutation({
    mutationFn: () => {
      if (!stage1Preview || !unbalanceSlot) throw new Error("No stage 1 allocation to save");
      const assignments: LptrSlotAssignment[] = stage1Preview.entries.map((e) => ({ blade_id: e.blade.id, slot_number: e.slot }));
      return batchService.assignLptrSlots(selectedBatch, 1, unbalanceSlot, LPTR_TOTAL_SLOTS, assignments);
    },
    onSuccess: (res) => {
      refresh();
      setStage1Preview(null);
      toast.success(res.message ?? "Stage 1 slots saved");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to save stage 1 slots";
      toast.error(msg);
    },
  });

  // ── Stage 2 ──────────────────────────────────────────────────────────────
  function handleRunStage2() {
    if (!unbalanceSlot) {
      toast.error("Record the empty rotor reading first");
      return;
    }
    if (stage1Slots.length === 0) {
      toast.error("Save Stage 1 first");
      return;
    }
    if (eligibleBlades.length < LPTR_STAGE2_COUNT) {
      toast.error(`Need ${LPTR_STAGE2_COUNT} remaining eligible blades, found ${eligibleBlades.length}`);
      return;
    }
    setStage2Preview(computeLptrStage2(eligibleBlades, unbalanceSlot, LPTR_TOTAL_SLOTS));
  }

  const saveStage2Mutation = useMutation({
    mutationFn: () => {
      if (!stage2Preview || !unbalanceSlot) throw new Error("No stage 2 allocation to save");
      const assignments: LptrSlotAssignment[] = stage2Preview.map((e) => ({ blade_id: e.blade.id, slot_number: e.slot }));
      return batchService.assignLptrSlots(selectedBatch, 2, unbalanceSlot, LPTR_TOTAL_SLOTS, assignments);
    },
    onSuccess: (res) => {
      refresh();
      setStage2Preview(null);
      toast.success(res.message ?? "Stage 2 slots saved");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to save stage 2 slots";
      toast.error(msg);
    },
  });

  // ── Balancing ────────────────────────────────────────────────────────────
  // Both mutations take an explicit work order number so they can fire
  // directly from a summary card (no need to select the batch and drill
  // into its Balancing tab first) as well as from within the tab itself.
  const completeBalancingMutation = useMutation({
    mutationFn: (workOrderNumber: string) => batchService.completeLptrBalancing(workOrderNumber),
    onSuccess: (res) => {
      refresh();
      toast.success(res.message ?? "LPTR balancing marked complete");
      // Stay on this batch/tab — the Balancing tab now shows "Send Back to
      // OH" as the next deliberate step, so the user doesn't have to hunt
      // for this same batch again later.
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to mark balancing complete";
      toast.error(msg);
    },
  });

  const returnToOhMutation = useMutation({
    mutationFn: (workOrderNumber: string) => batchService.returnToOh(workOrderNumber),
    onSuccess: (res) => {
      refresh();
      toast.success(res.message ?? "Work order sent back to OH");
      if (!res.work_order_number || res.work_order_number === selectedBatch) {
        setSelectedBatch("");
        setActiveTab("empty-rotor");
      }
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to send work order back to OH";
      toast.error(msg);
    },
  });

  const [exporting, setExporting] = useState(false);
  async function handleExport() {
    setExporting(true);
    try {
      await reportService.exportLptrSlots(selectedBatch);
    } catch {
      toast.error("Failed to export Excel file");
    } finally {
      setExporting(false);
    }
  }

  function handleBatchChange(bn: string) {
    setSelectedBatch(bn);
    setActiveTab("empty-rotor");
    setStage1Preview(null);
    setStage2Preview(null);
    setUnbalanceSlotInput("");
    setUnbalanceValueInput("");
  }

  const stage1SavedRows: SavedRow[] = useMemo(
    () => [...stage1Slots].sort((a, b) => parseInt(a.slot_number, 10) - parseInt(b.slot_number, 10)).map((s) => ({ slot: s, blade: bladeMap.get(s.blade_id) })),
    [stage1Slots, bladeMap]
  );
  const stage2SavedRows: SavedRow[] = useMemo(
    () => [...stage2Slots].sort((a, b) => parseInt(a.slot_number, 10) - parseInt(b.slot_number, 10)).map((s) => ({ slot: s, blade: bladeMap.get(s.blade_id) })),
    [stage2Slots, bladeMap]
  );

  const isLoading = bladesLoading || slotsLoading;

  // Jump to whichever tab matches this work order's actual progress: physical
  // balancing may happen an hour or a day after slots are saved, so reopening
  // an already-fully-slotted batch should land straight on Balancing instead
  // of making the user click back through Empty Rotor → Stage 1 → Stage 2
  // every time. Mirrors OHSlotAllocationPage's equivalent behavior for HPTR.
  useEffect(() => {
    if (!selectedBatch || isLoading || emptyRotorLoading) return;
    if (stage2Slots.length > 0) {
      setActiveTab("balancing");
    } else if (stage1Slots.length > 0) {
      setActiveTab("stage2");
    } else if (emptyRotor) {
      setActiveTab("stage1");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBatch, isLoading, emptyRotorLoading, stage2Slots.length, stage1Slots.length, emptyRotor]);

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <SlotAllocationIcon className="w-5 h-5 text-orange-500 shrink-0" />
              LPTR Slot Allocation
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight mt-0.5">
              Two-stage allocation — 46 blades, balancing check, then the remaining 44
            </p>
          </div>
          {selectedBatch && (
            <Button variant="outline" size="sm" onClick={refresh} className="w-full sm:w-auto justify-center border-slate-300 dark:border-slate-600">
              <RefreshCw className="w-4 h-4 mr-1.5" />Refresh
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 w-full px-4 sm:px-6 pt-5 pb-16 flex flex-col gap-5">
        <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
          <CardContent className="pt-5 pb-4">
            <div className="flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex-1 min-w-0">
                <Label className="text-sm font-semibold text-slate-600 dark:text-slate-300 mb-1.5 block">
                  Select Batch <span className="text-xs font-normal text-slate-400">(accepted batches only)</span>
                </Label>
                <select
                  value={selectedBatch}
                  onChange={(e) => handleBatchChange(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-background text-slate-900 dark:text-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                >
                  <option value="">— Select an accepted batch —</option>
                  {eligibleBatches.map((b) => (
                    <option key={b.work_order_number} value={b.work_order_number}>
                      {b.work_order_number}{` · ${b.current_status_label}`}
                    </option>
                  ))}
                </select>
                {eligibleBatches.length === 0 && (
                  <p className="text-xs text-amber-500 mt-1.5">
                    No accepted batches found. Batches must be accepted by Assembly before slot assignment.
                  </p>
                )}
              </div>
              {selectedBatch && stage1Slots.length > 0 && (
                <Button variant="outline" size="sm" onClick={handleExport} disabled={exporting} className="border-slate-300 dark:border-slate-600 shrink-0">
                  {exporting ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <FileSpreadsheet className="w-4 h-4 mr-1.5" />}
                  Export Excel
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {pendingBalancingBatches.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <ClipboardCheck className="w-3.5 h-3.5" />
              Pending Physical Balancing ({pendingBalancingBatches.length})
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {pendingBalancingBatches.map((b) => (
                <div
                  key={b.work_order_number}
                  className="rounded-xl border shadow-sm p-4 bg-white dark:bg-background border-slate-200 dark:border-slate-700/60"
                >
                  <div className="flex items-start justify-between mb-1.5">
                    <div>
                      <span className="font-mono font-semibold text-orange-500 dark:text-orange-400 text-sm">
                        {b.work_order_number}
                      </span>
                      {b.part_number && (
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{b.part_number}</p>
                      )}
                    </div>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full tabular-nums bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300">
                      {b.blade_count} blades
                    </span>
                  </div>
                  <Button
                    size="sm"
                    className="w-full text-xs h-8 mt-2 bg-amber-500 hover:bg-amber-400 text-white"
                    onClick={() => completeBalancingMutation.mutate(b.work_order_number)}
                    disabled={completeBalancingMutation.isPending && completeBalancingMutation.variables === b.work_order_number}
                  >
                    {completeBalancingMutation.isPending && completeBalancingMutation.variables === b.work_order_number ? (
                      <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                    ) : (
                      <Save className="w-3.5 h-3.5 mr-1.5" />
                    )}
                    Physical Balancing Confirmed
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}

        {pendingSendBackBatches.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-teal-600 dark:text-teal-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Send className="w-3.5 h-3.5" />
              Ready to Send Back to OH ({pendingSendBackBatches.length})
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {pendingSendBackBatches.map((b) => (
                <div
                  key={b.work_order_number}
                  className="rounded-xl border shadow-sm p-4 bg-white dark:bg-background border-slate-200 dark:border-slate-700/60"
                >
                  <div className="flex items-start justify-between mb-1.5">
                    <div>
                      <span className="font-mono font-semibold text-orange-500 dark:text-orange-400 text-sm">
                        {b.work_order_number}
                      </span>
                      {b.part_number && (
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{b.part_number}</p>
                      )}
                    </div>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full tabular-nums bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300">
                      {b.blade_count}/{b.blade_count}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-slate-200 dark:bg-background overflow-hidden mb-3">
                    <div className="h-full rounded-full bg-emerald-500" style={{ width: "100%" }} />
                  </div>
                  <Button
                    size="sm"
                    className="w-full text-xs h-8 bg-teal-500 hover:bg-teal-400 text-white"
                    onClick={() => returnToOhMutation.mutate(b.work_order_number)}
                    disabled={returnToOhMutation.isPending && returnToOhMutation.variables === b.work_order_number}
                  >
                    {returnToOhMutation.isPending && returnToOhMutation.variables === b.work_order_number ? (
                      <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                    ) : (
                      <Send className="w-3.5 h-3.5 mr-1.5" />
                    )}
                    Send Back to OH
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}

        {!selectedBatch && (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500 gap-3">
            <PackageSearch className="w-12 h-12 opacity-30" />
            <p className="text-sm">Select an accepted batch above to begin slot assignment</p>
          </div>
        )}

        {selectedBatch && (isLoading || emptyRotorLoading) && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-7 h-7 animate-spin text-orange-400" />
          </div>
        )}

        {selectedBatch && !isLoading && !emptyRotorLoading && (
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList>
              <TabsTrigger value="empty-rotor">Empty Rotor</TabsTrigger>
              <TabsTrigger value="stage1">Stage 1 (46)</TabsTrigger>
              <TabsTrigger value="stage2" disabled={stage1Slots.length === 0}>Stage 2 (44)</TabsTrigger>
              <TabsTrigger value="balancing" disabled={stage2Slots.length === 0}>Balancing</TabsTrigger>
            </TabsList>

            {/* ── Empty Rotor tab ────────────────────────────────────────── */}
            <TabsContent value="empty-rotor">
              <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Empty Rotor Balancing Reading</CardTitle>
                </CardHeader>
                <CardContent className="pt-0 space-y-4">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Before any blades are installed, the empty rotor is balanced. Enter the reported
                    unbalance position (the first of the two adjacent slots) and value.
                  </p>
                  {emptyRotor && (
                    <div className="rounded-lg border border-emerald-200 dark:border-emerald-700/50 bg-emerald-50 dark:bg-emerald-900/20 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300">
                      Saved: unbalance between slots {emptyRotor.unbalance_slot} and {(emptyRotor.unbalance_slot % LPTR_TOTAL_SLOTS) + 1}, {Number(emptyRotor.unbalance_value).toFixed(2)} g
                    </div>
                  )}
                  <div className="flex flex-wrap items-end gap-4">
                    <div className="space-y-1">
                      <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">Unbalance Slot</Label>
                      <Input
                        type="number" min={1} max={LPTR_TOTAL_SLOTS}
                        value={unbalanceSlotInput || String(emptyRotor?.unbalance_slot ?? "")}
                        onChange={(e) => setUnbalanceSlotInput(e.target.value)}
                        placeholder="e.g. 35"
                        className="w-32 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">Unbalance Value (g)</Label>
                      <Input
                        type="number" min={0} step="0.1"
                        value={unbalanceValueInput || String(emptyRotor?.unbalance_value ?? "")}
                        onChange={(e) => setUnbalanceValueInput(e.target.value)}
                        placeholder="e.g. 6.8"
                        className="w-32 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600"
                      />
                    </div>
                    <Button
                      onClick={() => saveEmptyRotorMutation.mutate()}
                      disabled={saveEmptyRotorMutation.isPending || (!unbalanceSlotInput && !emptyRotor) || (!unbalanceValueInput && !emptyRotor)}
                      className="bg-orange-500 hover:bg-orange-400 text-white"
                    >
                      {saveEmptyRotorMutation.isPending ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Save className="w-4 h-4 mr-1.5" />}
                      Save Reading
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* ── Stage 1 tab ────────────────────────────────────────────── */}
            <TabsContent value="stage1">
              <div className="space-y-5">
                {stage1Slots.length > 0 ? (
                  <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">Saved Stage 1 Slots ({stage1SavedRows.length})</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <SavedSlotsTable rows={stage1SavedRows} />
                    </CardContent>
                  </Card>
                ) : (
                  <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                    <CardContent className="py-10 flex flex-col items-center gap-4">
                      {!emptyRotor ? (
                        <p className="text-sm text-slate-400 dark:text-slate-500">Record the Empty Rotor reading first.</p>
                      ) : (
                        <>
                          <p className="text-sm text-slate-500 dark:text-slate-400 text-center">
                            {eligibleBlades.length} of {blades.length} LPTR blades ready. Stage 1 requires exactly {LPTR_STAGE1_COUNT}.
                          </p>
                          <Button onClick={handleRunStage1} disabled={eligibleBlades.length < LPTR_STAGE1_COUNT} className="bg-orange-500 hover:bg-orange-400 text-white">
                            <Play className="w-4 h-4 mr-1.5" />Run Stage 1 Allocation
                          </Button>
                        </>
                      )}
                    </CardContent>
                  </Card>
                )}

                {stage1Preview && stage1Slots.length === 0 && (
                  <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60 shadow-sm">
                    <CardHeader className="pb-2 flex flex-row items-center justify-between">
                      <CardTitle className="text-base">
                        Stage 1 Preview
                        <span className="ml-2 text-xs font-normal text-amber-500 bg-amber-50 dark:bg-amber-900/20 px-2 py-0.5 rounded-full">Not saved yet</span>
                      </CardTitle>
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => saveStage1Mutation.mutate()} disabled={saveStage1Mutation.isPending} className="bg-emerald-500 hover:bg-emerald-600 text-white">
                          {saveStage1Mutation.isPending ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1.5" />}
                          Save Stage 1
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0 space-y-2">
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Target weight for the opposite pair: {stage1Preview.targetWeight.toFixed(2)} g
                      </p>
                      <AllocationTable entries={stage1Preview.entries} />
                    </CardContent>
                  </Card>
                )}
              </div>
            </TabsContent>

            {/* ── Stage 2 tab ────────────────────────────────────────────── */}
            <TabsContent value="stage2">
              <div className="space-y-5">
                {stage1Slots.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 gap-3">
                    <Scale className="w-10 h-10 opacity-30" />
                    <p className="text-sm">Save Stage 1 first.</p>
                  </div>
                ) : stage2Slots.length > 0 ? (
                  <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">Saved Stage 2 Slots ({stage2SavedRows.length})</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <SavedSlotsTable rows={stage2SavedRows} />
                    </CardContent>
                  </Card>
                ) : (
                  <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                    <CardContent className="py-10 flex flex-col items-center gap-4">
                      <p className="text-sm text-slate-500 dark:text-slate-400 text-center">
                        {eligibleBlades.length} blade{eligibleBlades.length !== 1 ? "s" : ""} remaining. Stage 2 requires exactly {LPTR_STAGE2_COUNT}.
                      </p>
                      <Button onClick={handleRunStage2} disabled={eligibleBlades.length < LPTR_STAGE2_COUNT} className="bg-orange-500 hover:bg-orange-400 text-white">
                        <Play className="w-4 h-4 mr-1.5" />Run Stage 2 Allocation
                      </Button>
                    </CardContent>
                  </Card>
                )}

                {stage2Preview && stage2Slots.length === 0 && (
                  <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60 shadow-sm">
                    <CardHeader className="pb-2 flex flex-row items-center justify-between">
                      <CardTitle className="text-base">
                        Stage 2 Preview
                        <span className="ml-2 text-xs font-normal text-amber-500 bg-amber-50 dark:bg-amber-900/20 px-2 py-0.5 rounded-full">Not saved yet</span>
                      </CardTitle>
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => saveStage2Mutation.mutate()} disabled={saveStage2Mutation.isPending} className="bg-emerald-500 hover:bg-emerald-600 text-white">
                          {saveStage2Mutation.isPending ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1.5" />}
                          Save Stage 2
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <AllocationTable entries={stage2Preview} />
                    </CardContent>
                  </Card>
                )}
              </div>
            </TabsContent>

            {/* ── Balancing tab ────────────────────────────────────────────── */}
            <TabsContent value="balancing">
              {stage2Slots.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 gap-3">
                  <Scale className="w-10 h-10 opacity-30" />
                  <p className="text-sm">Save Stage 1 and Stage 2 first to track physical balancing here.</p>
                </div>
              ) : (
                <div className="space-y-5">
                  {!isBalanced && (
                    <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-base">Saved Slots ({stage1SavedRows.length + stage2SavedRows.length})</CardTitle>
                      </CardHeader>
                      <CardContent className="pt-0">
                        <SavedSlotsTable rows={[...stage1SavedRows, ...stage2SavedRows]} />
                      </CardContent>
                    </Card>
                  )}

                  {isBalanced ? (
                    <Card className="bg-white dark:bg-background border-teal-200 dark:border-teal-700/50">
                      <CardContent className="pt-5 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                        <div>
                          <p className="text-sm font-semibold text-teal-700 dark:text-teal-300">
                            Balancing confirmed — send back to OH?
                          </p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                            Report this work order's task complete and hand it back to OH. It stops
                            showing up in the accepted-batches selector above once sent.
                          </p>
                        </div>
                        <Button
                          onClick={() => returnToOhMutation.mutate(selectedBatch)}
                          disabled={returnToOhMutation.isPending}
                          className="bg-teal-500 hover:bg-teal-600 text-white shrink-0"
                        >
                          {returnToOhMutation.isPending ? (
                            <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                          ) : (
                            <Send className="w-4 h-4 mr-1.5" />
                          )}
                          Send Back to OH
                        </Button>
                      </CardContent>
                    </Card>
                  ) : (
                    <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                      <CardContent className="pt-5 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                        <div>
                          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                            Physical balancing confirmed?
                          </p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                            Save to mark this work order's LPTR balancing complete, then send it back to OH.
                          </p>
                        </div>
                        <Button
                          onClick={() => completeBalancingMutation.mutate(selectedBatch)}
                          disabled={completeBalancingMutation.isPending}
                          className="bg-emerald-500 hover:bg-emerald-600 text-white shrink-0"
                        >
                          {completeBalancingMutation.isPending ? (
                            <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                          ) : (
                            <Save className="w-4 h-4 mr-1.5" />
                          )}
                          Save
                        </Button>
                      </CardContent>
                    </Card>
                  )}
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}
      </div>
    </div>
  );
}
