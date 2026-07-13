import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, AlertTriangle, RefreshCw,
  PackageSearch, Play, Save, ArrowLeftRight, Scale, Lightbulb, FileSpreadsheet,
} from "lucide-react";
import { toast } from "sonner";
import { SlotAllocationIcon } from "@/components/common/CustomIcons";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { slotService } from "@/services/slotService";
import { reportService } from "@/services/reportService";
import type { BladeListItem, SlotAllocation } from "@/types";
import { cn } from "@/utils/cn";
import {
  HPTR_TOTAL_SLOTS, HPTR_TARGET_DIFF_MIN, HPTR_TARGET_DIFF_MAX,
  computeInitialHptrSlots, computeHalves, isSetMakingValid, computeAdjustedDiff,
  swapBladesBetweenSlots, groupByHalf, suggestBalancingSwap,
  type HptrAllocationEntry, type HptrHalves, type SwapSuggestion,
} from "@/utils/hptrBalancing";

// ─── Saved slots table ────────────────────────────────────────────────────────

interface SavedRow { slot: SlotAllocation; blade: BladeListItem | undefined; }

function SavedHalfTable({ title, rows }: { title: string; rows: SavedRow[] }) {
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between px-3 py-2 bg-slate-100 dark:bg-background rounded-t-lg border border-b-0 border-slate-200 dark:border-slate-700/60">
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</span>
        <span className="text-xs font-mono tabular-nums text-slate-500 dark:text-slate-400">{rows.length} slots</span>
      </div>
      <div className="border border-slate-200 dark:border-slate-700/60 rounded-b-lg overflow-x-auto">
        <table className="w-full text-sm whitespace-nowrap">
          <thead>
            <tr className="bg-slate-800 dark:bg-background">
              {["Slot", "Blade Serial", "Melt No.", "Weight (g)", "Static Moment (g·cm)"].map((h) => (
                <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-100 whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
            {rows.map(({ slot, blade }, idx) => (
              <tr
                key={slot.id}
                className={cn(
                  "transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/30",
                  idx % 2 === 0 ? "bg-white dark:bg-background" : "bg-slate-50/60 dark:bg-background"
                )}
              >
                <td className="px-3 py-2.5 font-mono font-bold text-cyan-600 dark:text-cyan-400 text-sm">
                  #{slot.slot_number}
                </td>
                <td className="px-3 py-2.5 font-mono text-orange-500 dark:text-orange-400 text-xs font-semibold">
                  {blade?.serial_number ?? "—"}
                </td>
                <td className="px-3 py-2.5 text-slate-600 dark:text-slate-300 text-xs">
                  {blade?.melt_number ?? "—"}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-xs">
                  {blade?.weight_grams != null ? Number(blade.weight_grams).toFixed(1) : "—"}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-xs">
                  {blade?.static_moment_gcm != null ? Number(blade.static_moment_gcm).toFixed(2) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SavedHptrSlotsTable({
  rows,
  totalSlots,
  batchNumber,
}: {
  rows: SavedRow[];
  totalSlots: number;
  batchNumber: string;
}) {
  const half = totalSlots / 2;
  const bySlot = (r: SavedRow) => parseInt(r.slot.slot_number, 10);
  const w1Rows = rows.filter((r) => { const n = bySlot(r); return !isNaN(n) && n <= half; }).sort((a, b) => bySlot(a) - bySlot(b));
  const w2Rows = rows.filter((r) => { const n = bySlot(r); return isNaN(n) || n > half; }).sort((a, b) => bySlot(a) - bySlot(b));
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    setExporting(true);
    try {
      await reportService.exportHptrSlots(batchNumber);
    } catch {
      toast.error("Failed to export Excel file");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60 shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center justify-between">
            <span>Saved HPTR Slot Assignments</span>
            <div className="flex items-center gap-3">
              <span className="text-sm font-normal text-slate-400">{rows.length} slots</span>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExport}
                disabled={exporting}
                className="border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300"
              >
                {exporting ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <FileSpreadsheet className="w-4 h-4 mr-1.5" />}
                Export Excel
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex flex-col lg:flex-row gap-4">
            <SavedHalfTable title={`W1 (Slots 1-${half})`} rows={w1Rows} />
            <SavedHalfTable title={`W2 (Slots ${half + 1}-${totalSlots})`} rows={w2Rows} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ─── Slot Allocation tab ───────────────────────────────────────────────────────

function SlotAllocationTab({
  eligibleCount,
  totalHptr,
  startSlot,
  setStartSlot,
  totalSlots,
  setTotalSlots,
  unbalanceValue,
  setUnbalanceValue,
  onRun,
  allocation,
  N,
}: {
  eligibleCount: number;
  totalHptr: number;
  startSlot: string;
  setStartSlot: (v: string) => void;
  totalSlots: string;
  setTotalSlots: (v: string) => void;
  unbalanceValue: string;
  setUnbalanceValue: (v: string) => void;
  onRun: () => void;
  allocation: HptrAllocationEntry[] | null;
  N: number;
}) {
  return (
    <div className="space-y-5">
      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
        <CardContent className="pt-5 pb-4 space-y-4">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {eligibleCount} of {totalHptr} HPTR blade{totalHptr !== 1 ? "s" : ""} in this batch have
            recorded measurements and are ready for slot allocation.
          </p>
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">
                Start Slot <span className="text-xs font-normal text-slate-400">(Assembly-provided rotor unbalanced slot)</span>
                <span className="text-red-500"> *</span>
              </Label>
              <Input
                type="number"
                min={1}
                max={N}
                value={startSlot}
                onChange={(e) => setStartSlot(e.target.value)}
                placeholder="e.g. 60"
                className="w-32 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">
                Total Slots on Rotor
              </Label>
              <Input
                type="number"
                min={2}
                value={totalSlots}
                onChange={(e) => setTotalSlots(e.target.value)}
                className="w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">
                Rotor Unbalance (g) <span className="text-xs font-normal text-slate-400">(used in Set Making target)</span>
              </Label>
              <Input
                type="number"
                step="0.1"
                value={unbalanceValue}
                onChange={(e) => setUnbalanceValue(e.target.value)}
                placeholder="e.g. 15"
                className="w-32 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <Button
              onClick={onRun}
              disabled={eligibleCount === 0}
              className="bg-orange-500 hover:bg-orange-400 text-white"
            >
              <Play className="w-4 h-4 mr-1.5" />
              Run Allocation
            </Button>
          </div>
        </CardContent>
      </Card>

      {allocation && (
        <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2 flex-wrap">
              <SlotAllocationIcon className="w-4 h-4 text-orange-500 shrink-0" />
              Computed Slot Assignments
              <span className="text-xs font-normal text-amber-500 bg-amber-50 dark:bg-amber-900/20 px-2 py-0.5 rounded-full">
                Preview — switch to Set Making to balance and save
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="bg-slate-800 dark:bg-background">
                    {["Slot", "Blade Serial", "Melt No.", "Weight (g)", "Static Moment (g·cm)"].map((h) => (
                      <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-100 whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                  {[...allocation].sort((a, b) => a.slot - b.slot).map(({ blade, slot }, idx) => (
                    <tr
                      key={blade.id}
                      className={cn(
                        "transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/30",
                        idx % 2 === 0 ? "bg-white dark:bg-background" : "bg-slate-50/60 dark:bg-background"
                      )}
                    >
                      <td className="px-3 py-2.5 font-mono font-bold text-cyan-600 dark:text-cyan-400 text-sm">#{slot}</td>
                      <td className="px-3 py-2.5 font-mono text-orange-500 dark:text-orange-400 text-xs font-semibold">
                        {blade.serial_number}
                      </td>
                      <td className="px-3 py-2.5 text-slate-600 dark:text-slate-300 text-xs">
                        {blade.melt_number ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 tabular-nums text-slate-700 dark:text-slate-200 text-xs">
                        {blade.weight_grams != null ? Number(blade.weight_grams).toFixed(1) : "—"}
                      </td>
                      <td className="px-3 py-2.5 tabular-nums text-slate-700 dark:text-slate-200 text-xs">
                        {blade.static_moment_gcm != null ? Number(blade.static_moment_gcm).toFixed(2) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ─── Set Making tab ────────────────────────────────────────────────────────────

function HalfColumn({ title, entries }: { title: string; entries: HptrAllocationEntry[] }) {
  const total = entries.reduce((sum, e) => sum + (e.blade.weight_grams ?? 0), 0);
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between px-3 py-2 bg-slate-100 dark:bg-background rounded-t-lg border border-b-0 border-slate-200 dark:border-slate-700/60">
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</span>
        <span className="text-xs font-mono tabular-nums text-slate-500 dark:text-slate-400">
          {total.toFixed(2)} g
        </span>
      </div>
      <div className="border border-slate-200 dark:border-slate-700/60 rounded-b-lg overflow-x-auto max-h-96 overflow-y-auto">
        <table className="w-full text-xs whitespace-nowrap">
          <thead className="sticky top-0 bg-slate-50 dark:bg-background">
            <tr>
              {["Slot", "Serial", "Weight (g)", "Static Moment (g·cm)"].map((h) => (
                <th key={h} className="px-2 py-2 text-left font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700/30">
            {entries.map(({ blade, slot }) => (
              <tr key={blade.id}>
                <td className="px-2 py-1.5 font-mono font-bold text-cyan-600 dark:text-cyan-400">#{slot}</td>
                <td className="px-2 py-1.5 font-mono text-orange-500 dark:text-orange-400">{blade.serial_number}</td>
                <td className="px-2 py-1.5 tabular-nums text-slate-700 dark:text-slate-200">
                  {blade.weight_grams != null ? Number(blade.weight_grams).toFixed(2) : "—"}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-slate-700 dark:text-slate-200">
                  {blade.static_moment_gcm != null ? Number(blade.static_moment_gcm).toFixed(2) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SetMakingTab({
  allocation,
  groups,
  halves,
  valid,
  unbalanceValue,
  swapA, setSwapA,
  swapB, setSwapB,
  onSwap,
  onSave,
  saving,
  suggestion,
  onSuggest,
  onApplySuggestion,
}: {
  allocation: HptrAllocationEntry[] | null;
  groups: { w1: HptrAllocationEntry[]; w2: HptrAllocationEntry[] } | null;
  halves: HptrHalves | null;
  valid: boolean;
  unbalanceValue: number;
  swapA: string; setSwapA: (v: string) => void;
  swapB: string; setSwapB: (v: string) => void;
  onSwap: () => void;
  onSave: () => void;
  saving: boolean;
  suggestion: SwapSuggestion | null;
  onSuggest: () => void;
  onApplySuggestion: () => void;
}) {
  if (!allocation || !groups || !halves) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 gap-3">
        <Scale className="w-10 h-10 opacity-30" />
        <p className="text-sm">Run the Slot Allocation tab first to generate the initial mapping.</p>
      </div>
    );
  }

  const adjustedDiff = computeAdjustedDiff(halves, unbalanceValue);

  return (
    <div className="space-y-5">
      {/* Validity banner */}
      <div className={cn(
        "rounded-xl border px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-4",
        valid
          ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-700/50"
          : "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-700/50"
      )}>
        <div className="flex items-center gap-3 flex-1">
          {valid
            ? <CheckCircle2 className="w-6 h-6 text-emerald-500 shrink-0" />
            : <AlertTriangle className="w-6 h-6 text-amber-500 shrink-0" />}
          <div>
            <p className={cn("font-semibold text-sm",
              valid ? "text-emerald-700 dark:text-emerald-300" : "text-amber-700 dark:text-amber-300"
            )}>
              {valid
                ? `Set is balanced — ${halves.startSlotHalf} is heavier, net of rotor unbalance by ${adjustedDiff.toFixed(2)} g`
                : `Not balanced yet — target ${halves.startSlotHalf} heavier, net of rotor unbalance, by ${HPTR_TARGET_DIFF_MIN}-${HPTR_TARGET_DIFF_MAX} g`}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              W1: {halves.w1Total.toFixed(2)} g · W2: {halves.w2Total.toFixed(2)} g · Diff (x): {halves.diff.toFixed(2)} g
              {" · "}Rotor unbalance (y): {unbalanceValue.toFixed(2)} g · |x − y|: {adjustedDiff.toFixed(2)} g
            </p>
          </div>
        </div>
      </div>

      {/* Swap controls */}
      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
        <CardContent className="pt-5 pb-4 space-y-4">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Manually swap the blades occupying two slots to adjust the W1/W2 balance. Slot numbers never change — only which blade sits in each.
          </p>

          {!valid && (
            <div className="rounded-lg border border-cyan-200 dark:border-cyan-700/50 bg-cyan-50 dark:bg-cyan-900/20 px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3">
              <Lightbulb className="w-5 h-5 text-cyan-500 shrink-0" />
              <div className="flex-1 min-w-0">
                {suggestion ? (
                  <>
                    <p className="text-sm font-medium text-cyan-700 dark:text-cyan-300">
                      {suggestion.flips.length === 1 ? "Suggested swap: " : `Suggested swaps (${suggestion.flips.length}): `}
                      {suggestion.flips.map((flip, i) => (
                        <span key={flip.pairIndex}>
                          {i > 0 && ", "}
                          <span className="font-mono">#{flip.slotA}</span> ({flip.bladeASerial}) ↔{" "}
                          <span className="font-mono">#{flip.slotB}</span> ({flip.bladeBSerial})
                        </span>
                      ))}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                      Resulting difference: {suggestion.resultingDiff.toFixed(2)} g
                      {suggestion.meetsTarget
                        ? " — meets the 1.5-2.0 g target"
                        : " — closest achievable; may need another swap after applying"}
                      {suggestion.usedNearPairs && " · used near-anchor pairs (fallback)"}
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Not balanced yet — get a suggested swap to help close the gap.
                  </p>
                )}
              </div>
              <div className="flex gap-2 shrink-0">
                {!suggestion && (
                  <Button variant="outline" size="sm" onClick={onSuggest}>
                    <Lightbulb className="w-4 h-4 mr-1.5" />
                    Suggest Swap
                  </Button>
                )}
                {suggestion && (
                  <Button size="sm" onClick={onApplySuggestion}
                    className="bg-cyan-500 hover:bg-cyan-600 text-white">
                    <ArrowLeftRight className="w-4 h-4 mr-1.5" />
                    Apply
                  </Button>
                )}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">Slot A</Label>
              <Input
                type="number"
                value={swapA}
                onChange={(e) => setSwapA(e.target.value)}
                placeholder="e.g. 12"
                className="w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">Slot B</Label>
              <Input
                type="number"
                value={swapB}
                onChange={(e) => setSwapB(e.target.value)}
                placeholder="e.g. 68"
                className="w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <Button variant="outline" onClick={onSwap} disabled={!swapA || !swapB || swapA === swapB}>
              <ArrowLeftRight className="w-4 h-4 mr-1.5" />
              Swap
            </Button>
            <div className="flex-1" />
            <Button
              onClick={onSave}
              disabled={saving}
              className="bg-emerald-500 hover:bg-emerald-600 text-white"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <Save className="w-4 h-4 mr-1.5" />}
              Save &amp; Assign Slots
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* W1 / W2 columns */}
      <div className="flex flex-col sm:flex-row gap-4">
        <HalfColumn title={`W1 (Slots 1–${halves.half})`} entries={groups.w1} />
        <HalfColumn title={`W2 (Slots ${halves.half + 1}–${halves.half * 2})`} entries={groups.w2} />
      </div>
    </div>
  );
}

// ─── Already-saved notice (shown on Slot Allocation / Set Making once saved) ───

function AlreadySavedNotice({ onGoToBalancing }: { onGoToBalancing: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 gap-3">
      <CheckCircle2 className="w-10 h-10 opacity-30" />
      <p className="text-sm text-center max-w-sm">
        This batch's HPTR slots are already saved. Track physical balancing or fix up a slot
        from the Balancing tab.
      </p>
      <Button variant="outline" size="sm" onClick={onGoToBalancing}>
        Go to Balancing
      </Button>
    </div>
  );
}

// ─── Balancing tab ──────────────────────────────────────────────────────────────

function BalancingTab({
  rows,
  totalSlots,
  batchNumber,
  onComplete,
  completing,
}: {
  rows: SavedRow[];
  totalSlots: number;
  batchNumber: string;
  onComplete: () => void;
  completing: boolean;
}) {
  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 gap-3">
        <Scale className="w-10 h-10 opacity-30" />
        <p className="text-sm">Save a slot allocation in Set Making first to track physical balancing here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <SavedHptrSlotsTable rows={rows} totalSlots={totalSlots} batchNumber={batchNumber} />

      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
        <CardContent className="pt-5 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Physical balancing confirmed?
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Save to mark this batch's HPTR balancing complete. It stops showing up in the batch
              selector above once saved.
            </p>
          </div>
          <Button
            onClick={onComplete}
            disabled={completing}
            className="bg-emerald-500 hover:bg-emerald-600 text-white shrink-0"
          >
            {completing ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <Save className="w-4 h-4 mr-1.5" />}
            Save
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function OHSlotAllocationPage() {
  const qc = useQueryClient();
  const [selectedBatch, setSelectedBatch] = useState("");
  const [startSlot, setStartSlot] = useState("");
  const [totalSlots, setTotalSlots] = useState(String(HPTR_TOTAL_SLOTS));
  const [unbalanceValue, setUnbalanceValue] = useState("");
  const [allocation, setAllocation] = useState<HptrAllocationEntry[] | null>(null);
  const [activeTab, setActiveTab] = useState("slot-allocation");
  const [swapA, setSwapA] = useState("");
  const [swapB, setSwapB] = useState("");
  const [suggestion, setSuggestion] = useState<SwapSuggestion | null>(null);

  const { data: allBatches = [] } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    staleTime: 30_000,
  });

  // Only offer batches that are a full, pure HPTR batch (all HPTR_TOTAL_SLOTS
  // blades are HPTR — no LPTR mixed in, no partial batch) and not yet marked
  // balancing-complete (Balancing tab's Save button). Batches with slots
  // already saved but not yet completed stay selectable too (not just the
  // currently-active one) so OH can come back later to continue physical
  // balancing or reject/redo — the Balancing tab, not the dropdown, is what
  // gates that state.
  const batches = useMemo(() => {
    const eligible = allBatches.filter(
      (b) =>
        b.blade_count === HPTR_TOTAL_SLOTS &&
        b.hptr_count === HPTR_TOTAL_SLOTS &&
        b.hptr_balanced_count < b.hptr_count
    );
    if (selectedBatch && !eligible.some((b) => b.batch_number === selectedBatch)) {
      const current = allBatches.find((b) => b.batch_number === selectedBatch);
      if (current) return [...eligible, current];
    }
    return eligible;
  }, [allBatches, selectedBatch]);

  const { data: hptrBladesData, isLoading: bladesLoading } = useQuery({
    queryKey: ["blades", "hptr-batch", selectedBatch],
    queryFn: () => bladeService.list({ batch_number: selectedBatch, blade_type: "HPTR", limit: 200 }),
    enabled: !!selectedBatch,
    staleTime: 0,
  });
  const hptrBlades: BladeListItem[] = hptrBladesData?.items ?? [];

  const { data: batchSlotsRaw = [], isLoading: slotsLoading } = useQuery({
    queryKey: ["slots", selectedBatch],
    queryFn: () => slotService.list({ batch_number: selectedBatch, limit: 200 }),
    enabled: !!selectedBatch,
    refetchInterval: 30_000,
  });

  const eligibleBlades = useMemo(
    () => hptrBlades.filter((b) => b.status === "MEASUREMENTS_RECORDED"),
    [hptrBlades]
  );
  const hptrBladeIds = useMemo(() => new Set(hptrBlades.map((b) => b.id)), [hptrBlades]);
  const savedHptrSlots = useMemo(
    () => batchSlotsRaw.filter((s) => s.is_active && hptrBladeIds.has(s.blade_id)),
    [batchSlotsRaw, hptrBladeIds]
  );
  const hasSavedSlots = savedHptrSlots.length > 0;
  const bladeMap = useMemo(() => {
    const m = new Map<string, BladeListItem>();
    hptrBlades.forEach((b) => m.set(b.id, b));
    return m;
  }, [hptrBlades]);

  const isLoading = bladesLoading || slotsLoading;

  const N = Math.max(2, parseInt(totalSlots, 10) || HPTR_TOTAL_SLOTS);
  const K = parseInt(startSlot, 10);
  const startSlotValid = K >= 1 && K <= N;
  const unbalanceNum = Number(unbalanceValue) || 0;

  const halves = allocation ? computeHalves(allocation, K, N) : null;
  const setMakingValid = halves ? isSetMakingValid(halves, unbalanceNum) : false;
  const groups = allocation ? groupByHalf(allocation, N) : null;

  function refresh() {
    qc.invalidateQueries({ queryKey: ["slots", selectedBatch] });
    qc.invalidateQueries({ queryKey: ["blades", "hptr-batch", selectedBatch] });
    qc.invalidateQueries({ queryKey: ["batches"] });
  }

  function handleRunAllocation() {
    if (!startSlotValid) {
      toast.error(`Enter a valid start slot (1-${N})`);
      return;
    }
    if (eligibleBlades.length === 0) {
      toast.error("No HPTR blades ready for slot allocation in this batch");
      return;
    }
    setAllocation(computeInitialHptrSlots(eligibleBlades, K, N));
    setSuggestion(null);
    setActiveTab("set-making");
  }

  function handleSwap() {
    const a = parseInt(swapA, 10);
    const b = parseInt(swapB, 10);
    if (!allocation || !a || !b || a === b) return;
    setAllocation(swapBladesBetweenSlots(allocation, a, b));
    setSwapA("");
    setSwapB("");
    setSuggestion(null);
  }

  function handleSuggest() {
    if (!allocation || !startSlotValid) return;
    const s = suggestBalancingSwap(allocation, K, unbalanceNum, N);
    if (!s) {
      toast.error("No eligible pair-flip found to suggest");
      return;
    }
    setSuggestion(s);
  }

  function handleApplySuggestion() {
    if (!allocation || !suggestion) return;
    const next = suggestion.flips.reduce(
      (acc, flip) => swapBladesBetweenSlots(acc, flip.slotA, flip.slotB),
      allocation
    );
    setAllocation(next);
    setSuggestion(null);
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!allocation) throw new Error("No allocation to save");
      return batchService.assignHptrSlots(
        selectedBatch,
        K,
        N,
        allocation.map((e) => ({ blade_id: e.blade.id, slot_number: e.slot })),
        unbalanceValue ? Number(unbalanceValue) : undefined
      );
    },
    onSuccess: (res) => {
      refresh();
      setAllocation(null);
      toast.success(res.message ?? "HPTR slots saved");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to save slots";
      toast.error(msg);
    },
  });

  const completeMutation = useMutation({
    mutationFn: () => batchService.completeHptrBalancing(selectedBatch),
    onSuccess: (res) => {
      refresh();
      toast.success(res.message ?? "HPTR balancing marked complete");
      setSelectedBatch("");
      setActiveTab("slot-allocation");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to mark balancing complete";
      toast.error(msg);
    },
  });

  function handleBatchChange(bn: string) {
    setSelectedBatch(bn);
    setAllocation(null);
    setStartSlot("");
    setSuggestion(null);
    setActiveTab("slot-allocation");
  }

  const savedRows: { slot: SlotAllocation; blade: BladeListItem | undefined }[] = useMemo(() => {
    return [...savedHptrSlots]
      .sort((a, b) => parseInt(a.slot_number, 10) - parseInt(b.slot_number, 10))
      .map((s) => ({ slot: s, blade: bladeMap.get(s.blade_id) }));
  }, [savedHptrSlots, bladeMap]);

  // Jump to whichever tab matches this batch's actual state: a batch with
  // slots already saved opens straight to Balancing; a fresh one opens to
  // Slot Allocation. Re-evaluated whenever the saved/unsaved state flips
  // (right after Save, or after Reject Batch resets it).
  useEffect(() => {
    if (!selectedBatch || isLoading) return;
    setActiveTab(hasSavedSlots ? "balancing" : "slot-allocation");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBatch, isLoading, hasSavedSlots]);

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <SlotAllocationIcon className="w-5 h-5 text-orange-500 shrink-0" />
              HPTR Slot Allocation &amp; Set Making
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight mt-0.5">
              HPTR blades stay in OH — slot allocation and set-making happen here, never in Assembly
            </p>
          </div>
          {selectedBatch && (
            <Button variant="outline" size="sm" onClick={refresh}
              className="w-full sm:w-auto justify-center border-slate-300 dark:border-slate-600">
              <RefreshCw className="w-4 h-4 mr-1.5" />Refresh
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 w-full px-4 sm:px-6 pt-5 pb-16 flex flex-col gap-5">
        {/* Batch selector */}
        <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
          <CardContent className="pt-5 pb-4">
            <Label className="text-sm font-semibold text-slate-600 dark:text-slate-300 mb-1.5 block">
              Select Batch
            </Label>
            <select
              value={selectedBatch}
              onChange={(e) => handleBatchChange(e.target.value)}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-background text-slate-900 dark:text-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
            >
              <option value="">— Select a batch —</option>
              {batches.map((b) => (
                <option key={b.batch_number} value={b.batch_number}>
                  {b.batch_number}{b.nomenclature ? ` · ${b.nomenclature}` : ""}
                </option>
              ))}
            </select>
          </CardContent>
        </Card>

        {!selectedBatch && (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500 gap-3">
            <PackageSearch className="w-12 h-12 opacity-30" />
            <p className="text-sm">Select a batch above to begin HPTR slot allocation</p>
          </div>
        )}

        {selectedBatch && isLoading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-7 h-7 animate-spin text-orange-400" />
          </div>
        )}

        {selectedBatch && !isLoading && hptrBlades.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500 gap-3">
            <PackageSearch className="w-12 h-12 opacity-30" />
            <p className="text-sm">No HPTR blades found in batch {selectedBatch}</p>
          </div>
        )}

        {selectedBatch && !isLoading && hptrBlades.length > 0 && (
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList>
              <TabsTrigger value="slot-allocation">Slot Allocation</TabsTrigger>
              <TabsTrigger value="set-making">Set Making</TabsTrigger>
              <TabsTrigger value="balancing">Balancing</TabsTrigger>
            </TabsList>

            <TabsContent value="slot-allocation">
              {hasSavedSlots ? (
                <AlreadySavedNotice onGoToBalancing={() => setActiveTab("balancing")} />
              ) : (
                <SlotAllocationTab
                  eligibleCount={eligibleBlades.length}
                  totalHptr={hptrBlades.length}
                  startSlot={startSlot}
                  setStartSlot={setStartSlot}
                  totalSlots={totalSlots}
                  setTotalSlots={setTotalSlots}
                  unbalanceValue={unbalanceValue}
                  setUnbalanceValue={setUnbalanceValue}
                  onRun={handleRunAllocation}
                  allocation={allocation}
                  N={N}
                />
              )}
            </TabsContent>

            <TabsContent value="set-making">
              {hasSavedSlots ? (
                <AlreadySavedNotice onGoToBalancing={() => setActiveTab("balancing")} />
              ) : (
                <SetMakingTab
                  allocation={allocation}
                  groups={groups}
                  halves={halves}
                  valid={setMakingValid}
                  unbalanceValue={unbalanceNum}
                  swapA={swapA} setSwapA={setSwapA}
                  swapB={swapB} setSwapB={setSwapB}
                  onSwap={handleSwap}
                  onSave={() => saveMutation.mutate()}
                  saving={saveMutation.isPending}
                  suggestion={suggestion}
                  onSuggest={handleSuggest}
                  onApplySuggestion={handleApplySuggestion}
                />
              )}
            </TabsContent>

            <TabsContent value="balancing">
              <BalancingTab
                rows={savedRows}
                totalSlots={N}
                batchNumber={selectedBatch}
                onComplete={() => completeMutation.mutate()}
                completing={completeMutation.isPending}
              />
            </TabsContent>
          </Tabs>
        )}
      </div>
    </div>
  );
}
