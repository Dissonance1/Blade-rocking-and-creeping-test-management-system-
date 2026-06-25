import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Package,
  Check,
  Pencil,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertCircle,
  LayoutGrid,
  PackageSearch,
} from "lucide-react";
import { format, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { slotService } from "@/services/slotService";
import { extractApiError } from "@/services/api";
import { BalancingSuggestion } from "@/components/BalancingSuggestion";
import type { BladeListItem, SlotAllocation } from "@/types";
import { cn } from "@/utils/cn";

// ─── Schema ───────────────────────────────────────────────────────────────────

const slotSchema = z.object({
  slot_number: z.string().min(1, "Slot number required"),
  balancing_remarks: z.string().optional(),
  is_balanced: z.boolean().default(false),
});
type SlotFormValues = z.infer<typeof slotSchema>;

// ─── Blade row ────────────────────────────────────────────────────────────────

function BladeRow({
  blade,
  selected,
  onClick,
}: {
  blade: BladeListItem;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-xl border px-4 py-3 transition-colors",
        selected
          ? "border-orange-500 bg-orange-50 dark:bg-orange-500/10"
          : "border-slate-200 dark:border-slate-700/50 bg-white dark:bg-slate-800/40 hover:border-slate-300 dark:hover:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700/30"
      )}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono font-semibold text-orange-500 dark:text-orange-400 text-sm">
          {blade.serial_number}
        </span>
        {selected && <Check className="w-4 h-4 text-orange-500" />}
      </div>
      <div className="text-slate-500 dark:text-slate-400 text-xs mt-1 space-y-0.5">
        <div>Melt: {blade.melt_number}</div>
        <div>{blade.part_number} · {blade.nomenclature}</div>
      </div>
    </button>
  );
}

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
  const queryClient = useQueryClient();
  const [remarks, setRemarks] = useState(slot?.balancing_remarks ?? "");
  const [isBalanced, setIsBalanced] = useState(slot?.is_balanced ?? false);

  const updateMutation = useMutation({
    mutationFn: () =>
      slotService.update(slot!.id, {
        balancing_remarks: remarks,
        is_balanced: isBalanced,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["slots"] });
      onClose();
    },
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white max-w-md">
        <DialogHeader>
          <DialogTitle className="text-slate-900 dark:text-white">Update Balancing — Slot {slot?.slot_number}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Balancing Remarks</Label>
            <Textarea
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
            />
          </div>
          <div className="flex items-center gap-3">
            <Checkbox
              id="balanced"
              checked={isBalanced}
              onCheckedChange={(v) => setIsBalanced(!!v)}
            />
            <Label htmlFor="balanced" className="text-slate-600 dark:text-slate-300 text-sm cursor-pointer">
              Mark as balanced
            </Label>
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
          >
            Cancel
          </Button>
          <Button
            onClick={() => updateMutation.mutate()}
            disabled={updateMutation.isPending}
            className="bg-emerald-500 hover:bg-emerald-600 text-white"
          >
            {updateMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Check className="w-4 h-4" />
            )}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function SlotAllocationPage() {
  const queryClient = useQueryClient();
  const [selectedBlade, setSelectedBlade] = useState<BladeListItem | null>(null);
  const [editSlot, setEditSlot] = useState<SlotAllocation | null>(null);
  const [balancingBatch, setBalancingBatch] = useState<string>("");

  // Only blades pending slot assignment — status filter keeps result set small
  const { data: bladesData } = useQuery({
    queryKey: ["blades", "sent-to-assembly"],
    queryFn: () => bladeService.list({ status: "SENT_TO_ASSEMBLY", limit: 500 }),
    refetchInterval: 30_000,
  });

  const { data: batches = [] } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    staleTime: 60_000,
  });

  // Per-batch blades for balancing suggestion — only fetched when a batch is selected
  const { data: balancingBladesData } = useQuery({
    queryKey: ["blades", "balancing-batch", balancingBatch],
    queryFn: () => bladeService.list({ batch_number: balancingBatch!, limit: 200 }),
    enabled: !!balancingBatch,
    staleTime: 0,
  });

  const assignSlotMutation = useMutation({
    mutationFn: ({ imbalanceSlot, totalSlots }: { imbalanceSlot: number; totalSlots: number }) =>
      batchService.assignSlot(balancingBatch, imbalanceSlot, totalSlots),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["blades"] });
      queryClient.invalidateQueries({ queryKey: ["slots"] });
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      import("sonner").then(({ toast }) => toast.success(result.message));
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to assign slots";
      import("sonner").then(({ toast }) => toast.error(msg));
    },
  });

  const { data: slotsData = [] } = useQuery({
    queryKey: ["slots"],
    queryFn: () => slotService.list({ limit: 200 }),
    refetchInterval: 15_000,
  });

  const pendingBlades = bladesData?.items ?? [];
  const slots: import("@/types").SlotAllocation[] = Array.isArray(slotsData) ? slotsData : [];

  const balancingBlades = balancingBladesData?.items ?? [];

  const actionableBatches = useMemo(
    () => batches.filter((b) =>
      ["ACCEPTED", "RECEIVED_BY_ASSEMBLY", "SENT_TO_ASSEMBLY", "MODIFIED", "REJECTED"].includes(b.current_status)
    ),
    [batches]
  );

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<SlotFormValues>({
    resolver: zodResolver(slotSchema),
    defaultValues: { is_balanced: false },
  });

  const isBalancedVal = watch("is_balanced");

  const assignMutation = useMutation({
    mutationFn: async (values: SlotFormValues) => {
      const slot = await slotService.create({
        blade_id: selectedBlade!.id,
        slot_number: values.slot_number,
      });
      // Apply balancing fields as a follow-up update if needed
      if (values.balancing_remarks || values.is_balanced) {
        await slotService.update(slot.id, {
          ...(values.balancing_remarks ? { balancing_remarks: values.balancing_remarks } : {}),
          is_balanced: values.is_balanced,
        });
      }
      return slot;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["slots", "blades"] });
      reset();
      setSelectedBlade(null);
    },
  });

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">
      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm">
        <div className="max-w-screen-xl mx-auto">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <LayoutGrid className="w-5 h-5 text-orange-500" />
            Slot Allocation
          </h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">
            Assign blades to assembly slots for balancing
          </p>
        </div>
      </div>

      <div className="max-w-screen-xl mx-auto px-6 py-6 space-y-8">
        {/* Balancing suggestion — batch-level slot assignment */}
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <PackageSearch className="w-4 h-4 text-slate-500 dark:text-slate-400" />
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              Batch Slot Assignment &amp; Balancing
            </p>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={balancingBatch}
              onChange={(e) => setBalancingBatch(e.target.value)}
              className="rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 min-w-[200px]"
            >
              <option value="">— Select a batch —</option>
              {actionableBatches.map((b) => (
                <option key={b.batch_number} value={b.batch_number}>
                  {b.batch_number} · {b.current_status_label}
                </option>
              ))}
            </select>
            {balancingBatch && balancingBlades.length > 0 && (
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {balancingBlades.length} blades in batch
              </span>
            )}
          </div>
          {balancingBatch && (
            <BalancingSuggestion
              blades={balancingBlades}
              slots={slots}
              onAssign={(imbalanceSlot, totalSlots) =>
                assignSlotMutation.mutate({ imbalanceSlot, totalSlots })
              }
              isAssigning={assignSlotMutation.isPending}
            />
          )}
        </div>

        {/* Top panel: blade list + form */}
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
          {/* Left — blade list */}
          <div className="xl:col-span-2">
            <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm h-full">
              <CardHeader className="pb-3">
                <CardTitle className="text-slate-900 dark:text-white text-base flex items-center justify-between">
                  <span>Pending Slot Assignment</span>
                  <span className="text-sm font-normal text-slate-500 dark:text-slate-400">
                    {pendingBlades.length} blades
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 max-h-[500px] overflow-y-auto">
                {pendingBlades.length === 0 ? (
                  <div className="text-center py-10 text-slate-400 dark:text-slate-500">
                    <Package className="w-10 h-10 mx-auto mb-2 opacity-30" />
                    <p className="text-sm">No blades awaiting slot assignment</p>
                  </div>
                ) : (
                  pendingBlades.map((blade) => (
                    <BladeRow
                      key={blade.id}
                      blade={blade}
                      selected={selectedBlade?.id === blade.id}
                      onClick={() => setSelectedBlade(blade)}
                    />
                  ))
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right — slot form */}
          <div className="xl:col-span-3">
            <Card
              className={cn(
                "bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm h-full transition-opacity",
                !selectedBlade && "opacity-50 pointer-events-none"
              )}
            >
              <CardHeader className="pb-3">
                <CardTitle className="text-slate-900 dark:text-white text-base">
                  {selectedBlade ? (
                    <>
                      Assign Slot —{" "}
                      <span className="text-orange-500 dark:text-orange-400 font-mono">
                        {selectedBlade.serial_number}
                      </span>
                    </>
                  ) : (
                    "Select a blade to assign a slot"
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmit((v) => assignMutation.mutate(v))} className="space-y-4">
                  <div className="space-y-1.5">
                    <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">
                      Slot Number <span className="text-red-500">*</span>
                    </Label>
                    <Input
                      type="number"
                      min={1}
                      placeholder="e.g. 12"
                      className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                      {...register("slot_number")}
                    />
                    {errors.slot_number && (
                      <p className="text-red-500 dark:text-red-400 text-xs">
                        {errors.slot_number.message?.toString()}
                      </p>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Balancing Remarks</Label>
                    <Textarea
                      placeholder="Enter any balancing notes…"
                      className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white min-h-[80px]"
                      {...register("balancing_remarks")}
                    />
                  </div>

                  <div className="flex items-center gap-3">
                    <Checkbox
                      id="is_balanced"
                      checked={isBalancedVal}
                      onCheckedChange={(v) => setValue("is_balanced", !!v)}
                    />
                    <Label
                      htmlFor="is_balanced"
                      className="text-slate-600 dark:text-slate-300 text-sm cursor-pointer"
                    >
                      Mark as balanced immediately
                    </Label>
                  </div>

                  {assignMutation.isError && (
                    <Alert
                      variant="destructive"
                      className="border-red-500/50 bg-red-50 dark:bg-red-500/10"
                    >
                      <AlertCircle className="h-4 w-4 text-red-500" />
                      <AlertDescription className="text-red-700 dark:text-red-300">
                        {extractApiError(assignMutation.error)}
                      </AlertDescription>
                    </Alert>
                  )}

                  <Button
                    type="submit"
                    disabled={!selectedBlade || assignMutation.isPending}
                    className="w-full bg-orange-500 hover:bg-orange-600 text-white"
                  >
                    {assignMutation.isPending ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Package className="w-4 h-4" />
                    )}
                    Assign Slot
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Bottom — active slot allocations table */}
        <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-slate-900 dark:text-white text-base flex items-center justify-between">
              <span>Active Slot Allocations</span>
              <span className="text-sm font-normal text-slate-500 dark:text-slate-400">
                {slots.filter((s) => s.is_active).length} active
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {slots.length === 0 ? (
              <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-sm">
                No slot allocations recorded yet
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-800 dark:bg-slate-700">
                    <tr>
                      {[
                        "Slot",
                        "Blade Serial",
                        "Balanced",
                        "Allocated",
                        "Actions",
                      ].map((h) => (
                        <th
                          key={h}
                          className={cn(
                            "px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase text-left",
                            h === "Actions" && "text-right"
                          )}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-700/50">
                    {slots.map((slot, rowIdx) => (
                      <tr
                        key={slot.id}
                        className={cn(
                          "transition-colors hover:bg-blue-50 dark:hover:bg-slate-700/30",
                          rowIdx % 2 === 0 ? "bg-white dark:bg-slate-800/40" : "bg-slate-50 dark:bg-slate-800/20"
                        )}
                      >
                        <td className="px-4 py-3 font-mono font-bold text-cyan-600 dark:text-cyan-400">
                          #{slot.slot_number}
                        </td>
                        <td className="px-4 py-3 font-mono text-orange-500 dark:text-orange-400 text-xs">
                          {slot.blade_id}
                        </td>
                        <td className="px-4 py-3">
                          {slot.is_balanced ? (
                            <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                          ) : (
                            <XCircle className="w-5 h-5 text-slate-400 dark:text-slate-500" />
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-500 dark:text-slate-400 text-xs">
                          {format(parseISO(slot.allocated_at), "dd MMM yyyy HH:mm")}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setEditSlot(slot)}
                              className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white h-8 px-2"
                            >
                              <Pencil className="w-3 h-3" />
                              Update
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <UpdateBalancingDialog
        slot={editSlot}
        open={!!editSlot}
        onClose={() => setEditSlot(null)}
      />
    </div>
  );
}
