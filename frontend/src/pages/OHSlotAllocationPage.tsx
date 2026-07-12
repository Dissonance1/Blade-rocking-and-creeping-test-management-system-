import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, AlertTriangle, RefreshCw,
  PackageSearch, Play, Save, ArrowLeftRight, Scale, Pencil, Lightbulb,
  XCircle, ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";
import { SlotAllocationIcon } from "@/components/common/CustomIcons";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { slotService } from "@/services/slotService";
import type { BladeListItem, SlotAllocation } from "@/types";
import { cn } from "@/utils/cn";
import {
  HPTR_TOTAL_SLOTS, HPTR_TARGET_DIFF_MIN, HPTR_TARGET_DIFF_MAX,
  computeInitialHptrSlots, computeHalves, isSetMakingValid,
  swapBladesBetweenSlots, groupByHalf, suggestBalancingSwap,
  type HptrAllocationEntry, type HptrHalves, type SwapSuggestion,
} from "@/utils/hptrBalancing";

// ─── Update balancing dialog (reused for saved HPTR slots) ────────────────────

function UpdateBalancingDialog({
  slot,
  open,
  onClose,
}: {
  slot: SlotAllocation | null;
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [remarks, setRemarks] = useState(slot?.balancing_remarks ?? "");
  const [isBalanced, setIsBalanced] = useState(slot?.is_balanced ?? false);

  const mutation = useMutation({
    mutationFn: () =>
      slotService.update(slot!.id, { is_balanced: isBalanced, balancing_remarks: remarks }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["slots"] });
      toast.success(`Slot ${slot?.slot_number} updated`);
      onClose();
    },
    onError: () => toast.error("Failed to update balancing"),
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-white dark:bg-background border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white max-w-md">
        <DialogHeader>
          <DialogTitle>Update Balancing — Slot {slot?.slot_number}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="flex items-center gap-3">
            <Checkbox
              id="hptr-balanced"
              checked={isBalanced}
              onCheckedChange={(v) => setIsBalanced(!!v)}
            />
            <Label htmlFor="hptr-balanced" className="text-sm cursor-pointer">Mark as balanced</Label>
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm font-medium">Remarks</Label>
            <Textarea
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              placeholder="Enter balancing notes…"
              className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}
            className="bg-emerald-500 hover:bg-emerald-600 text-white">
            {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <CheckCircle2 className="w-4 h-4 mr-1" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Saved slots table ────────────────────────────────────────────────────────

interface SavedRow { slot: SlotAllocation; blade: BladeListItem | undefined; }

function SavedHptrSlotsTable({
  rows,
  totalSlots,
  onEdit,
}: {
  rows: SavedRow[];
  totalSlots: number;
  onEdit: (s: SlotAllocation) => void;
}) {
  const half = totalSlots / 2;
  const balancedCount = rows.filter((r) => r.slot.is_balanced).length;
  const unbalancedCount = rows.length - balancedCount;
  const allBalanced = rows.length > 0 && unbalancedCount === 0;

  return (
    <div className="space-y-4">
      <div className={cn(
        "rounded-xl border px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-4",
        allBalanced
          ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-700/50"
          : "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-700/50"
      )}>
        <div className="flex items-center gap-3 flex-1">
          {allBalanced
            ? <CheckCircle2 className="w-6 h-6 text-emerald-500 shrink-0" />
            : <AlertTriangle className="w-6 h-6 text-amber-500 shrink-0" />}
          <div>
            <p className={cn("font-semibold text-sm",
              allBalanced ? "text-emerald-700 dark:text-emerald-300" : "text-amber-700 dark:text-amber-300"
            )}>
              {allBalanced
                ? `All ${rows.length} HPTR blades balanced`
                : `${unbalancedCount} blade${unbalancedCount > 1 ? "s" : ""} not yet balanced`}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              {balancedCount} balanced · {unbalancedCount} unbalanced · {rows.length} total
            </p>
          </div>
        </div>
      </div>

      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60 shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center justify-between">
            <span>Saved HPTR Slot Assignments</span>
            <span className="text-sm font-normal text-slate-400">{rows.length} slots</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
              <thead>
                <tr className="bg-slate-800 dark:bg-background">
                  {["Slot", "Half", "Blade Serial", "Melt No.", "Weight (g)", "Action"].map((h) => (
                    <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-100 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                {rows.map(({ slot, blade }, idx) => {
                  const slotNum = parseInt(slot.slot_number, 10);
                  const inW1 = !isNaN(slotNum) && slotNum <= half;
                  return (
                    <tr
                      key={slot.id}
                      className={cn(
                        "transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/30",
                        !slot.is_balanced ? "bg-red-50/40 dark:bg-red-900/10"
                          : idx % 2 === 0 ? "bg-white dark:bg-background"
                            : "bg-slate-50/60 dark:bg-background"
                      )}
                    >
                      <td className="px-3 py-2.5 font-mono font-bold text-cyan-600 dark:text-cyan-400 text-sm">
                        #{slot.slot_number}
                      </td>
                      <td className="px-3 py-2.5 text-xs">
                        <span className={cn(
                          "inline-flex items-center rounded-full px-2 py-0.5 font-semibold",
                          inW1 ? "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                            : "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                        )}>
                          {inW1 ? "W1" : "W2"}
                        </span>
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
                      <td className="px-3 py-2.5">
                        <Button
                          variant="ghost" size="sm"
                          onClick={() => onEdit(slot)}
                          className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white h-7 px-2 text-xs"
                        >
                          <Pencil className="w-3 h-3 mr-1" />Update
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
                Rotor Unbalance (g) <span className="text-xs font-normal text-slate-400">(reference only)</span>
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
                    {["Slot", "Blade Serial", "Melt No.", "Weight (g)"].map((h) => (
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
              {["Slot", "Serial", "Weight (g)"].map((h) => (
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
                ? `Set is balanced — ${halves.startSlotHalf} is heavier by ${halves.diff.toFixed(2)} g`
                : `Not balanced yet — target ${halves.startSlotHalf} heavier by ${HPTR_TARGET_DIFF_MIN}-${HPTR_TARGET_DIFF_MAX} g`}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              W1: {halves.w1Total.toFixed(2)} g · W2: {halves.w2Total.toFixed(2)} g · Difference: {halves.diff.toFixed(2)} g
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
                      Suggested swap: <span className="font-mono">#{suggestion.slotA}</span> ({suggestion.bladeASerial}) ↔{" "}
                      <span className="font-mono">#{suggestion.slotB}</span> ({suggestion.bladeBSerial})
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                      Resulting difference: {suggestion.resultingDiff.toFixed(2)} g
                      {suggestion.meetsTarget
                        ? " — meets the 1.5-2.0 g target"
                        : " — closest achievable with one swap; may need another swap after applying"}
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Not balanced yet — get a suggested swap to help close the gap.
                  </p>
                )}
              </div>
              <div className="flex gap-2 shrink-0">
                <Button variant="outline" size="sm" onClick={onSuggest}>
                  <Lightbulb className="w-4 h-4 mr-1.5" />
                  {suggestion ? "Re-suggest" : "Suggest Swap"}
                </Button>
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
        This batch's HPTR slots are already saved. Track physical balancing, fix up a slot, or
        reject and redo from the Balancing tab.
      </p>
      <Button variant="outline" size="sm" onClick={onGoToBalancing}>
        Go to Balancing
      </Button>
    </div>
  );
}

// ─── Reject batch dialog ───────────────────────────────────────────────────────

function RejectHptrSlotsDialog({
  open,
  onClose,
  onConfirm,
  pending,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  pending: boolean;
}) {
  const [reason, setReason] = useState("");

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-white dark:bg-background border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-600 dark:text-red-400">
            <ShieldAlert className="w-5 h-5" />
            Reject Batch — Redo Slot Allocation
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2 text-sm text-slate-600 dark:text-slate-300">
          <p>
            This deactivates all saved HPTR slot assignments for this batch and resets every
            blade back to <span className="font-semibold">Measurements Recorded</span>. Slot
            Allocation becomes available again to redo from scratch with a new unbalanced slot.
          </p>
          <div className="space-y-1.5">
            <Label className="text-sm font-medium">Reason (optional)</Label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Physical balancing test still showed rotor unbalanced…"
              className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => onConfirm(reason)}
            disabled={pending}
            className="bg-red-600 hover:bg-red-500 text-white"
          >
            {pending ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <XCircle className="w-4 h-4 mr-1.5" />}
            Reject &amp; Redo
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Balancing tab ──────────────────────────────────────────────────────────────

function BalancingTab({
  rows,
  totalSlots,
  onEditRow,
  fixSwapA, setFixSwapA,
  fixSwapB, setFixSwapB,
  fixReason, setFixReason,
  onFixSwap,
  fixSwapPending,
  onOpenReject,
}: {
  rows: SavedRow[];
  totalSlots: number;
  onEditRow: (s: SlotAllocation) => void;
  fixSwapA: string; setFixSwapA: (v: string) => void;
  fixSwapB: string; setFixSwapB: (v: string) => void;
  fixReason: string; setFixReason: (v: string) => void;
  onFixSwap: () => void;
  fixSwapPending: boolean;
  onOpenReject: () => void;
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
      <SavedHptrSlotsTable rows={rows} totalSlots={totalSlots} onEdit={onEditRow} />

      {/* Fix-up swap after a failed physical balancing test */}
      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
        <CardContent className="pt-5 pb-4 space-y-4">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            If physical balancing testing shows a blade still unbalanced, swap it with another
            slot's blade. Both slots are already full, so this exchanges the two — it saves
            immediately (unlike the Set Making swap, which only edits the preview).
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">Slot A</Label>
              <Input
                value={fixSwapA}
                onChange={(e) => setFixSwapA(e.target.value)}
                placeholder="e.g. 12"
                className="w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">Slot B</Label>
              <Input
                value={fixSwapB}
                onChange={(e) => setFixSwapB(e.target.value)}
                placeholder="e.g. 68"
                className="w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <div className="space-y-1 flex-1 min-w-[200px]">
              <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">Reason</Label>
              <Input
                value={fixReason}
                onChange={(e) => setFixReason(e.target.value)}
                placeholder="e.g. Slot 12 failed balancing test"
                className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
              />
            </div>
            <Button
              variant="outline"
              onClick={onFixSwap}
              disabled={!fixSwapA || !fixSwapB || fixSwapA === fixSwapB || fixReason.trim().length < 5 || fixSwapPending}
            >
              {fixSwapPending ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <ArrowLeftRight className="w-4 h-4 mr-1.5" />}
              Swap &amp; Save
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Reject the whole batch and redo */}
      <Card className="bg-red-50/50 dark:bg-red-900/10 border-red-200 dark:border-red-700/50">
        <CardContent className="pt-5 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-300">
              Still can't balance the set?
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Reject this batch's slot allocation to reset every blade and redo Slot Allocation
              from scratch with a new unbalanced slot.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={onOpenReject}
            className="border-2 border-red-400 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/10 shrink-0"
          >
            <ShieldAlert className="w-4 h-4 mr-1.5" />
            Reject Batch
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
  const [editSlot, setEditSlot] = useState<SlotAllocation | null>(null);
  const [suggestion, setSuggestion] = useState<SwapSuggestion | null>(null);
  const [fixSwapA, setFixSwapA] = useState("");
  const [fixSwapB, setFixSwapB] = useState("");
  const [fixReason, setFixReason] = useState("");
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);

  const { data: allBatches = [] } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    staleTime: 30_000,
  });

  // Only offer batches that are a full, pure HPTR batch (all HPTR_TOTAL_SLOTS
  // blades are HPTR — no LPTR mixed in, no partial batch). Batches with slots
  // already saved stay selectable too (not just the currently-active one) so
  // OH can come back later to continue physical balancing or reject/redo —
  // the Balancing tab, not the dropdown, is what gates that state.
  const batches = useMemo(() => {
    const eligible = allBatches.filter(
      (b) => b.blade_count === HPTR_TOTAL_SLOTS && b.hptr_count === HPTR_TOTAL_SLOTS
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

  const halves = allocation ? computeHalves(allocation, K, N) : null;
  const setMakingValid = halves ? isSetMakingValid(halves) : false;
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
    const s = suggestBalancingSwap(allocation, K, N);
    if (!s) {
      toast.error("No cross-half swap found to suggest");
      return;
    }
    setSuggestion(s);
  }

  function handleApplySuggestion() {
    if (!allocation || !suggestion) return;
    setAllocation(swapBladesBetweenSlots(allocation, suggestion.slotA, suggestion.slotB));
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

  const fixSwapMutation = useMutation({
    mutationFn: () =>
      slotService.swap({
        slot_number_a: fixSwapA,
        slot_number_b: fixSwapB,
        blade_type: "HPTR",
        batch_number: selectedBatch,
        reason: fixReason,
      }),
    onSuccess: () => {
      refresh();
      setFixSwapA("");
      setFixSwapB("");
      setFixReason("");
      toast.success(`Slots ${fixSwapA} and ${fixSwapB} swapped`);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to swap slots";
      toast.error(msg);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (reason: string) => batchService.rejectHptrSlots(selectedBatch, reason || undefined),
    onSuccess: (res) => {
      refresh();
      setRejectDialogOpen(false);
      toast.success(res.message ?? "HPTR slot allocation rejected");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to reject batch";
      toast.error(msg);
    },
  });

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
                onEditRow={setEditSlot}
                fixSwapA={fixSwapA} setFixSwapA={setFixSwapA}
                fixSwapB={fixSwapB} setFixSwapB={setFixSwapB}
                fixReason={fixReason} setFixReason={setFixReason}
                onFixSwap={() => fixSwapMutation.mutate()}
                fixSwapPending={fixSwapMutation.isPending}
                onOpenReject={() => setRejectDialogOpen(true)}
              />
            </TabsContent>
          </Tabs>
        )}
      </div>

      <UpdateBalancingDialog
        key={editSlot?.id ?? ""}
        slot={editSlot}
        open={!!editSlot}
        onClose={() => setEditSlot(null)}
      />

      <RejectHptrSlotsDialog
        open={rejectDialogOpen}
        onClose={() => setRejectDialogOpen(false)}
        onConfirm={(reason) => rejectMutation.mutate(reason)}
        pending={rejectMutation.isPending}
      />
    </div>
  );
}
