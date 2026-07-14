import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, XCircle, AlertTriangle,
  RefreshCw, Pencil, Check, PackageSearch, XOctagon, Play, Save,
} from "lucide-react";
import { toast } from "sonner";
import { SlotAllocationIcon } from "@/components/common/CustomIcons";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { slotService } from "@/services/slotService";
import type { SlotAllocation, BladeListItem } from "@/types";
import { cn } from "@/utils/cn";
import { computeBalancedSlots, type PreviewRow } from "@/utils/balancing";

// ─── Update balancing dialog ──────────────────────────────────────────────────

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
              id="balanced"
              checked={isBalanced}
              onCheckedChange={(v) => setIsBalanced(!!v)}
            />
            <Label htmlFor="balanced" className="text-sm cursor-pointer">Mark as balanced</Label>
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
            {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Reject batch dialog ──────────────────────────────────────────────────────

function RejectBatchDialog({
  workOrderNumber,
  open,
  onClose,
}: {
  workOrderNumber: string;
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [remarks, setRemarks] = useState("");

  const mutation = useMutation({
    mutationFn: () => batchService.reject(workOrderNumber, remarks),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["batches"] });
      qc.invalidateQueries({ queryKey: ["blades"] });
      toast.success(`Work Order ${workOrderNumber} rejected`);
      onClose();
    },
    onError: () => toast.error("Failed to reject batch"),
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-white dark:bg-background border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-500">
            <XOctagon className="w-5 h-5" />
            Reject Work Order {workOrderNumber}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            This will reject the entire batch and notify OH. Please state the reason clearly.
          </p>
          <div className="space-y-1.5">
            <Label className="text-sm font-medium text-red-500">Rejection Reason *</Label>
            <Textarea
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              placeholder="Describe why the batch is being rejected…"
              className="border-red-300 dark:border-red-700/50 min-h-[100px]"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !remarks.trim()}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <XOctagon className="w-4 h-4 mr-1" />}
            Confirm Reject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Preview table (before saving) ───────────────────────────────────────────

function PreviewTable({
  rows,
  onSave,
  onReject,
  saving,
}: {
  rows: PreviewRow[];
  onSave: () => void;
  onReject: () => void;
  saving: boolean;
}) {
  return (
    <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60 shadow-sm">
      <CardHeader className="pb-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <CardTitle className="text-base flex items-center gap-2 flex-wrap">
          <SlotAllocationIcon className="w-4 h-4 text-orange-500 shrink-0" />
          Computed Slot Assignments
          <span className="text-xs font-normal text-amber-500 bg-amber-50 dark:bg-amber-900/20 px-2 py-0.5 rounded-full">
            Preview — not saved yet
          </span>
        </CardTitle>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={onReject}
            variant="outline"
            size="sm"
            className="flex-1 sm:flex-none justify-center border-red-300 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
          >
            <XOctagon className="w-3.5 h-3.5 mr-1.5" />
            Reject Batch
          </Button>
          <Button
            onClick={onSave}
            disabled={saving}
            size="sm"
            className="flex-1 sm:flex-none justify-center bg-emerald-500 hover:bg-emerald-600 text-white"
          >
            {saving ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
            ) : (
              <Save className="w-3.5 h-3.5 mr-1.5" />
            )}
            Save Slots
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="bg-slate-800 dark:bg-background">
                {["Slot", "Blade Serial", "Melt No.", "Static Moment (g·cm)", "Weight (g)", "H1 (mm)", "H2 (mm)", "H3 (mm)", "H4 (mm)"].map((h) => (
                  <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-100 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
              {rows.map(({ blade, slot }, idx) => {
                const hd = blade.height_data ?? {};
                return (
                  <tr
                    key={blade.id}
                    className={cn(
                      "transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/30",
                      idx % 2 === 0 ? "bg-white dark:bg-background" : "bg-slate-50/60 dark:bg-background"
                    )}
                  >
                    <td className="px-3 py-2.5 font-mono font-bold text-cyan-600 dark:text-cyan-400 text-sm">
                      #{slot}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-orange-500 dark:text-orange-400 text-xs font-semibold">
                      {blade.serial_number}
                    </td>
                    <td className="px-3 py-2.5 text-slate-600 dark:text-slate-300 text-xs">
                      {blade.melt_number ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-slate-700 dark:text-slate-200 text-xs">
                      {blade.static_moment_gcm != null ? Number(blade.static_moment_gcm).toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-slate-700 dark:text-slate-200 text-xs">
                      {blade.weight_grams != null ? Number(blade.weight_grams).toFixed(1) : "—"}
                    </td>
                    {(["H1", "H2", "H3", "H4"] as const).map((pos) => (
                      <td key={pos} className="px-3 py-2.5 tabular-nums text-slate-600 dark:text-slate-300 text-xs">
                        {hd[pos] != null ? Number(hd[pos]).toFixed(3) : "—"}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Saved slots table ────────────────────────────────────────────────────────

interface SlotRow { slot: SlotAllocation; blade: BladeListItem | undefined; }

function SavedSlotsTable({
  rows,
  onEdit,
  onReject,
}: {
  rows: SlotRow[];
  onEdit: (s: SlotAllocation) => void;
  onReject: () => void;
}) {
  const balancedCount = rows.filter((r) => r.slot.is_balanced).length;
  const unbalancedCount = rows.filter((r) => !r.slot.is_balanced).length;
  const allBalanced = rows.length > 0 && unbalancedCount === 0;

  return (
    <div className="space-y-4">
      {/* Summary bar */}
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
                ? `All ${rows.length} blades balanced — batch ready`
                : `${unbalancedCount} blade${unbalancedCount > 1 ? "s" : ""} not yet balanced`}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              {balancedCount} balanced · {unbalancedCount} unbalanced · {rows.length} total
            </p>
          </div>
        </div>
        <div className="w-full sm:w-48">
          <div className="h-2.5 rounded-full bg-slate-200 dark:bg-background overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all", allBalanced ? "bg-emerald-500" : "bg-amber-400")}
              style={{ width: `${Math.round((balancedCount / rows.length) * 100)}%` }}
            />
          </div>
          <p className="text-xs text-right text-slate-400 mt-0.5">
            {Math.round((balancedCount / rows.length) * 100)}%
          </p>
        </div>
        {unbalancedCount > 0 && (
          <Button onClick={onReject} className="bg-red-600 hover:bg-red-700 text-white shrink-0">
            <XOctagon className="w-4 h-4 mr-2" />
            Reject Batch
          </Button>
        )}
      </div>

      {/* Slots table */}
      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60 shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center justify-between">
            <span>Saved Slot Assignments</span>
            <span className="text-sm font-normal text-slate-400">{rows.length} slots</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
              <thead>
                <tr className="bg-slate-800 dark:bg-background">
                  {["Slot", "Blade Serial", "Melt No.", "Weight (g)", "H1 (mm)", "H2 (mm)", "H3 (mm)", "H4 (mm)", "Balance", "Remarks", "Action"].map((h) => (
                    <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-100 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                {rows.map(({ slot, blade }, idx) => {
                  const hd = blade?.height_data ?? {};
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
                      <td className="px-3 py-2.5 font-mono text-orange-500 dark:text-orange-400 text-xs font-semibold">
                        {blade?.serial_number ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 text-slate-600 dark:text-slate-300 text-xs">
                        {blade?.melt_number ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 tabular-nums text-xs">
                        {blade?.weight_grams != null ? Number(blade.weight_grams).toFixed(1) : "—"}
                      </td>
                      {(["H1", "H2", "H3", "H4"] as const).map((pos) => (
                        <td key={pos} className="px-3 py-2.5 tabular-nums text-slate-600 dark:text-slate-300 text-xs">
                          {hd[pos] != null ? Number(hd[pos]).toFixed(3) : "—"}
                        </td>
                      ))}
                      <td className="px-3 py-2.5">
                        {slot.is_balanced ? (
                          <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 className="w-4 h-4" />Balanced
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-500 dark:text-red-400">
                            <XCircle className="w-4 h-4" />Unbalanced
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-slate-500 dark:text-slate-400 max-w-[160px] truncate">
                        {slot.balancing_remarks || "—"}
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

// ─── Main page ────────────────────────────────────────────────────────────────

export default function SlotAllocationPage() {
  const qc = useQueryClient();
  const [selectedBatch, setSelectedBatch] = useState("");
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [editSlot, setEditSlot] = useState<SlotAllocation | null>(null);
  const [showReject, setShowReject] = useState(false);

  // Accepted batches only
  const { data: batches = [] } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    staleTime: 30_000,
  });
  const eligibleBatches = useMemo(
    () => batches.filter((b) => ["ACCEPTED", "MODIFIED"].includes(b.current_status)),
    [batches]
  );

  // Blades in selected batch
  const { data: bladesData, isLoading: bladesLoading } = useQuery({
    queryKey: ["blades", "batch", selectedBatch],
    queryFn: () => bladeService.list({ work_order_number: selectedBatch, limit: 200 }),
    enabled: !!selectedBatch,
    staleTime: 0,
  });
  const blades: BladeListItem[] = bladesData?.items ?? [];

  // Saved slot allocations — scoped to selected batch server-side
  const { data: batchSlotsRaw = [], isLoading: slotsLoading } = useQuery({
    queryKey: ["slots", selectedBatch],
    queryFn: () => slotService.list({ work_order_number: selectedBatch, limit: 200 }),
    enabled: !!selectedBatch,
    refetchInterval: 30_000,
  });

  const bladeMap = useMemo(() => {
    const m = new Map<string, BladeListItem>();
    blades.forEach((b) => m.set(b.id, b));
    return m;
  }, [blades]);

  // Saved slots for this batch sorted by slot number
  const batchSlots: SlotRow[] = useMemo(() => {
    return [...batchSlotsRaw]
      .sort((a, b) => {
        const na = parseInt(a.slot_number, 10), nb = parseInt(b.slot_number, 10);
        return isNaN(na) || isNaN(nb) ? a.slot_number.localeCompare(b.slot_number) : na - nb;
      })
      .map((s) => ({ slot: s, blade: bladeMap.get(s.blade_id) }));
  }, [batchSlotsRaw, bladeMap]);

  const hasSavedSlots = batchSlots.length > 0;
  const isLoading = bladesLoading || slotsLoading;
  const batchInfo = batches.find((b) => b.work_order_number === selectedBatch);

  // Save slots mutation
  const saveMutation = useMutation({
    mutationFn: () => batchService.assignSlot(selectedBatch, 1, 90),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["slots", selectedBatch] });
      qc.invalidateQueries({ queryKey: ["blades", "batch", selectedBatch] });
      setPreview(null);
      toast.success(res.message ?? "Slots saved");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to save slots";
      toast.error(msg);
    },
  });

  function handleRunBalancing() {
    if (blades.length === 0) {
      toast.error("No blades loaded for this batch");
      return;
    }
    const rows = computeBalancedSlots(blades, 1, 90);
    setPreview(rows);
  }

  function handleBatchChange(bn: string) {
    setSelectedBatch(bn);
    setPreview(null);
  }

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <SlotAllocationIcon className="w-5 h-5 text-orange-500 shrink-0" />
              LPTR Slot Allocation
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight mt-0.5">
              Run the balancing algorithm, review computed slots, then save or reject
            </p>
          </div>
          {selectedBatch && (
            <Button variant="outline" size="sm"
              onClick={() => { qc.invalidateQueries({ queryKey: ["slots"] }); qc.invalidateQueries({ queryKey: ["blades", "batch", selectedBatch] }); }}
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
                      {b.work_order_number}
                      {b.nomenclature ? ` · ${b.nomenclature}` : ""}
                      {` · ${b.current_status_label}`}
                    </option>
                  ))}
                </select>
                {eligibleBatches.length === 0 && (
                  <p className="text-xs text-amber-500 mt-1.5">
                    No accepted batches found. Batches must be accepted by Assembly before slot assignment.
                  </p>
                )}
              </div>
              {batchInfo && (
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="px-3 py-1.5 rounded-full bg-slate-100 dark:bg-background text-slate-600 dark:text-slate-300 font-medium">
                    {batchInfo.blade_count} blades
                  </span>
                  {batchInfo.work_order_number && (
                    <span className="px-3 py-1.5 rounded-full bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400 font-medium">
                      WO: {batchInfo.work_order_number}
                    </span>
                  )}
                  {batchInfo.part_number && (
                    <span className="px-3 py-1.5 rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 font-medium">
                      P/N: {batchInfo.part_number}
                    </span>
                  )}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* No batch selected */}
        {!selectedBatch && (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500 gap-3">
            <PackageSearch className="w-12 h-12 opacity-30" />
            <p className="text-sm">Select an accepted batch above to begin slot assignment</p>
          </div>
        )}

        {/* Loading */}
        {selectedBatch && isLoading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-7 h-7 animate-spin text-orange-400" />
          </div>
        )}

        {/* === SAVED SLOTS VIEW === */}
        {selectedBatch && !isLoading && hasSavedSlots && (
          <SavedSlotsTable
            rows={batchSlots}
            onEdit={setEditSlot}
            onReject={() => setShowReject(true)}
          />
        )}

        {/* === NO SLOTS YET — RUN BALANCING === */}
        {selectedBatch && !isLoading && !hasSavedSlots && !preview && (
          <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
            <CardContent className="py-14 flex flex-col items-center gap-5">
              <SlotAllocationIcon className="w-12 h-12 text-orange-300 dark:text-orange-700" />
              <div className="text-center">
                <p className="font-semibold text-slate-700 dark:text-slate-200 text-lg">
                  No slots assigned yet
                </p>
                <p className="text-sm text-slate-400 dark:text-slate-500 mt-1 max-w-sm">
                  Click the button below to compute balanced disc slot assignments for
                  all {blades.length} blade{blades.length !== 1 ? "s" : ""} in this batch.
                  You can review before saving.
                </p>
              </div>
              <Button
                onClick={handleRunBalancing}
                disabled={blades.length === 0}
                className="w-full sm:w-auto justify-center bg-orange-500 hover:bg-orange-400 text-white px-6 sm:px-10 py-3 sm:py-5 text-sm sm:text-base"
              >
                <Play className="w-5 h-5 mr-2 shrink-0" />
                Run Balancing Algorithm
              </Button>
            </CardContent>
          </Card>
        )}

        {/* === PREVIEW VIEW === */}
        {selectedBatch && !isLoading && !hasSavedSlots && preview && (
          <>
            <div className="flex items-center gap-2 text-sm text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/50 rounded-lg px-4 py-3">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>
                This is a <strong>preview only</strong> — slots have not been saved yet.
                Review the assignments below, then click <strong>Save Slots</strong> to confirm or <strong>Reject Batch</strong> if the assignments are not acceptable.
              </span>
            </div>
            <PreviewTable
              rows={preview}
              onSave={() => saveMutation.mutate()}
              onReject={() => setShowReject(true)}
              saving={saveMutation.isPending}
            />
          </>
        )}
      </div>

      {/* Dialogs */}
      <UpdateBalancingDialog
        key={editSlot?.id ?? ""}
        slot={editSlot}
        open={!!editSlot}
        onClose={() => setEditSlot(null)}
      />
      {selectedBatch && (
        <RejectBatchDialog
          workOrderNumber={selectedBatch}
          open={showReject}
          onClose={() => setShowReject(false)}
        />
      )}
    </div>
  );
}
