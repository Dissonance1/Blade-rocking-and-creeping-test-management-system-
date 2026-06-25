import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  ExternalLink,
  ArrowRight,
  RotateCcw,
  Download,
  Inbox,
  CheckCircle2,
  XCircle,
  Loader2,
  Package,
  Send,
  AlertTriangle,
  Trash2,
} from "lucide-react";
import { formatDistanceToNow, differenceInDays, parseISO } from "date-fns";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import type { BladeStatus } from "@/types";
import { cn } from "@/utils/cn";

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_VARIANTS: Partial<Record<BladeStatus, string>> = {
  CREATED: "bg-indigo-500 text-white",
  OH_INSPECTION: "bg-amber-500 text-white",
  MEASUREMENTS_RECORDED: "bg-blue-500 text-white",
  SENT_TO_ASSEMBLY: "bg-violet-500 text-white",
  REJECTED: "bg-red-500 text-white",
  COMPLETED: "bg-emerald-500 text-white",
  ON_HOLD: "bg-slate-500 text-white",
  REOPENED: "bg-amber-500 text-white",
};

function StatusBadge({ status }: { status: BladeStatus }) {
  const cls = STATUS_VARIANTS[status] ?? "bg-slate-500 text-white";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
        cls
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

// ─── Tab config ───────────────────────────────────────────────────────────────

const TABS: Array<{
  id: string;
  label: string;
  icon: React.ReactNode;
  statuses: BladeStatus[];
}> = [
  {
    // All blades still at OH — awaiting measurements OR measurements done but batch not yet sent
    id: "active",
    label: "Active",
    icon: <Inbox className="w-4 h-4" />,
    statuses: ["CREATED", "OH_INSPECTION", "MEASUREMENTS_RECORDED", "REOPENED"],
  },
  {
    id: "sent",
    label: "Sent to Assembly",
    icon: <ArrowRight className="w-4 h-4" />,
    statuses: ["SENT_TO_ASSEMBLY"],
  },
  {
    id: "completed",
    label: "Completed",
    icon: <CheckCircle2 className="w-4 h-4" />,
    statuses: ["COMPLETED"],
  },
];

const BATCH_MAX = 90;

// ─── Send Batch Confirmation Dialog ──────────────────────────────────────────

interface SendBatchDialogProps {
  batchNumber: string | null;
  /** OH-eligible blades (these will actually be sent) */
  bladeCount: number;
  /** Total blades in batch (for display) */
  totalBladeCount: number;
  onConfirm: () => void;
  onClose: () => void;
  isLoading: boolean;
}

function SendBatchDialog({
  batchNumber,
  bladeCount,
  totalBladeCount,
  onConfirm,
  onClose,
  isLoading,
}: SendBatchDialogProps) {
  const remaining = BATCH_MAX - bladeCount;
  const isFull = bladeCount >= BATCH_MAX;
  const alreadySent = bladeCount === 0 && totalBladeCount > 0;

  return (
    <Dialog open={!!batchNumber} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 max-w-md">
        <DialogHeader>
          <DialogTitle className="text-slate-900 dark:text-white flex items-center gap-2">
            <Send className="w-5 h-5 text-violet-500" />
            Send Batch to Assembly
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Batch info */}
          <div className="rounded-lg bg-slate-100 dark:bg-slate-700/40 p-3 text-sm space-y-1">
            <div className="flex justify-between">
              <span className="text-slate-500 dark:text-slate-400">Batch</span>
              <span className="font-semibold font-mono text-orange-500 dark:text-orange-300">
                {batchNumber}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500 dark:text-slate-400">Total blades in batch</span>
              <span className="font-semibold tabular-nums text-slate-700 dark:text-slate-300">
                {totalBladeCount}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500 dark:text-slate-400">Ready to send (OH-side)</span>
              <span className={cn(
                "font-semibold tabular-nums",
                alreadySent ? "text-slate-400" : isFull ? "text-emerald-500" : "text-amber-500"
              )}>
                {bladeCount}
              </span>
            </div>
          </div>

          {/* Progress bar — only when there are sendable blades */}
          {!alreadySent && (
            <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", isFull ? "bg-emerald-500" : "bg-amber-400")}
                style={{ width: `${Math.min((bladeCount / BATCH_MAX) * 100, 100)}%` }}
              />
            </div>
          )}

          {/* Already sent to Assembly */}
          {alreadySent && (
            <div className="flex items-start gap-2 rounded-lg bg-slate-100 dark:bg-slate-700/40 border border-slate-300 dark:border-slate-600 p-3 text-sm">
              <CheckCircle2 className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
              <p className="text-slate-600 dark:text-slate-300">
                All blades in this batch have already been sent to Assembly.
                No action needed.
              </p>
            </div>
          )}

          {/* Warning if not full — still allows sending */}
          {!alreadySent && !isFull && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 p-3 text-sm">
              <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <div className="text-amber-700 dark:text-amber-300">
                <p className="font-semibold">{bladeCount} of {totalBladeCount} blades are ready (OH-side).</p>
                <p className="mt-1">
                  <strong>{remaining}</strong> blade{remaining !== 1 ? "s" : ""} still not at OH stage.
                  Send the current <strong>{bladeCount}</strong> to Assembly now?
                </p>
              </div>
            </div>
          )}

          {!alreadySent && isFull && (
            <div className="flex items-start gap-2 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 p-3 text-sm">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" />
              <p className="text-emerald-700 dark:text-emerald-300">
                All <strong>{totalBladeCount}</strong> blades are ready. Good to send to Assembly.
              </p>
            </div>
          )}
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isLoading}
            className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300"
          >
            {alreadySent ? "Close" : "No, Cancel"}
          </Button>
          {!alreadySent && (
            <Button
              onClick={onConfirm}
              disabled={isLoading}
              className="bg-violet-600 hover:bg-violet-500 text-white"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
              ) : (
                <Send className="w-4 h-4 mr-1.5" />
              )}
              Yes, Send to Assembly
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function OHQueuePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("active");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchFilter, setBatchFilter] = useState<string>("");
  const [sendBatchTarget, setSendBatchTarget] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Batch list — drives cards, dropdown, and counts
  const { data: batches = [] } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  // Per-batch blade fetch — only runs when a batch is selected
  const { data, isLoading } = useQuery({
    queryKey: ["blades", "oh-queue-batch", batchFilter],
    queryFn: () => bladeService.list({ batch_number: batchFilter!, limit: 200 }),
    enabled: !!batchFilter,
    staleTime: 0,
  });

  const sendToAssemblyMutation = useMutation({
    mutationFn: (bladeId: string) =>
      bladeService.transition(bladeId, {
        to_status: "SENT_TO_ASSEMBLY",
        remarks: "Forwarded to Assembly Shop from OH Station",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["blades"] }),
  });

  const reopenMutation = useMutation({
    mutationFn: (bladeId: string) =>
      bladeService.transition(bladeId, {
        to_status: "REOPENED",
        remarks: "Reopened from OH Station",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["blades"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (bladeId: string) => bladeService.deleteBlade(bladeId),
    onSuccess: () => {
      toast.success("Blade permanently deleted");
      setConfirmDeleteId(null);
      queryClient.invalidateQueries({ queryKey: ["blades", "oh-queue-batch", batchFilter] });
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to delete blade");
      setConfirmDeleteId(null);
    },
  });

  const sendBatchMutation = useMutation({
    mutationFn: (batchNumber: string) =>
      batchService.sendToAssembly(batchNumber, `Batch ${batchNumber} sent to Assembly from OH`),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["blades"] });
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      setSendBatchTarget(null);
      toast.success(result.message);
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to send batch to Assembly";
      toast.error(msg);
      setSendBatchTarget(null);
    },
  });

  const currentTab = TABS.find((t) => t.id === activeTab) ?? TABS[0]!;

  // Only populated when a batch is selected — no pagination issues
  const allBlades = data?.items ?? [];

  // All batch numbers from the batch list — not limited by blade pagination
  const batchNumbers = useMemo(
    () => [...new Set(batches.map((b) => b.batch_number))].sort(),
    [batches]
  );

  const filtered = useMemo(() => {
    if (!currentTab) return [];
    const q = search.toLowerCase();
    return allBlades
      .filter((b) => currentTab.statuses.includes(b.status))
      .filter(
        (b) =>
          !q ||
          b.serial_number.toLowerCase().includes(q) ||
          (b.melt_number ?? "").toLowerCase().includes(q)
      );
  }, [allBlades, activeTab, search, currentTab]);

  // Total blades in selected batch — from batch summary (always accurate)
  const batchBladeCount = useMemo(
    () => batches.find((b) => b.batch_number === batchFilter)?.blade_count ?? 0,
    [batches, batchFilter]
  );

  // Fetch the target batch's blades directly when the dialog opens.
  // Using allBlades (limit 500) would miss batches beyond the first page when
  // total blade count exceeds 500. A targeted query is always accurate.
  const OH_ELIGIBLE: BladeStatus[] = ["CREATED", "OH_INSPECTION", "MEASUREMENTS_RECORDED", "REOPENED"];
  const { data: batchBladesData } = useQuery({
    queryKey: ["blades", "batch-dialog", sendBatchTarget],
    queryFn: () => bladeService.list({ batch_number: sendBatchTarget!, limit: 500 }),
    enabled: !!sendBatchTarget,
    staleTime: 0,
  });

  const sendBatchBladeCount = useMemo(() => {
    if (!sendBatchTarget || !batchBladesData) return 0;
    return batchBladesData.items.filter((b) => OH_ELIGIBLE.includes(b.status)).length;
  }, [batchBladesData, sendBatchTarget]);

  const sendBatchTotalCount = useMemo(() => {
    if (!sendBatchTarget) return 0;
    return batches.find((b) => b.batch_number === sendBatchTarget)?.blade_count ?? 0;
  }, [batches, sendBatchTarget]);

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const tabCount = (statuses: BladeStatus[]) =>
    allBlades
      .filter((b) => statuses.includes(b.status))
      .filter((b) => !batchFilter || b.batch_number === batchFilter).length;

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">
      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm">
        <div className="flex items-center justify-between max-w-screen-xl mx-auto flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">OH Station Queue</h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">Overhaul station blade management</p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            {selected.size > 0 && (
              <Button
                variant="outline"
                size="sm"
                className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                <Download className="w-4 h-4" />
                Export {selected.size} selected
              </Button>
            )}
            {/* Send Batch to Assembly button — shown when a batch filter is active */}
            {batchFilter && (
              <Button
                size="sm"
                className="bg-violet-600 hover:bg-violet-500 text-white"
                onClick={() => setSendBatchTarget(batchFilter)}
              >
                <Send className="w-4 h-4 mr-1.5" />
                Send Batch to Assembly
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-screen-xl mx-auto px-6 py-6">
        {/* Filters row */}
        <div className="flex flex-wrap gap-3 mb-5">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 dark:text-slate-400" />
            <Input
              placeholder="Search serial or melt number…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-slate-50 dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500"
            />
          </div>

          {/* Batch filter */}
          <div className="flex items-center gap-2">
            <Package className="w-4 h-4 text-slate-500 dark:text-slate-400 flex-shrink-0" />
            <select
              value={batchFilter}
              onChange={(e) => setBatchFilter(e.target.value)}
              className="rounded-md border border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 min-w-[160px]"
            >
              <option value="">All Batches</option>
              {batchNumbers.map((bn) => (
                <option key={bn} value={bn}>
                  {bn}
                </option>
              ))}
            </select>
          </div>

          {/* Batch info chip */}
          {batchFilter && (
            <div className="flex items-center gap-2 rounded-full bg-violet-100 dark:bg-violet-500/20 border border-violet-300 dark:border-violet-500/40 px-3 py-1 text-sm">
              <span className="text-violet-700 dark:text-violet-300 font-medium">
                {batchBladeCount}/{BATCH_MAX} blades
              </span>
              {batchBladeCount >= BATCH_MAX && (
                <span className="text-emerald-500 text-xs font-semibold">Full</span>
              )}
              <button
                onClick={() => setBatchFilter("")}
                className="text-violet-500 hover:text-violet-700 dark:hover:text-violet-200 text-xs ml-1"
              >
                ✕
              </button>
            </div>
          )}
        </div>

        {/* ── Batch Overview ──────────────────────────────────────────────── */}
        {batches.filter((b) => b.current_status === "CREATED" || b.current_status === "REJECTED").length > 0 && (
          <div className="mb-5">
            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Package className="w-3.5 h-3.5" />
              Batches — click Send when ready
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {batches
                .filter((b) => b.current_status === "CREATED" || b.current_status === "REJECTED")
                .map((batch) => {
                  const isRejected = batch.current_status === "REJECTED";
                  const pct = Math.min((batch.blade_count / BATCH_MAX) * 100, 100);
                  const isFull = batch.blade_count >= BATCH_MAX;
                  const remaining = BATCH_MAX - batch.blade_count;
                  return (
                    <div
                      key={batch.batch_number}
                      className={cn(
                        "rounded-xl border shadow-sm p-4",
                        isRejected
                          ? "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30"
                          : "bg-white dark:bg-slate-800/60 border-slate-200 dark:border-slate-700/60"
                      )}
                    >
                      <div className="flex items-start justify-between mb-1.5">
                        <div>
                          <button
                            onClick={() => setBatchFilter(batch.batch_number)}
                            className="font-mono font-semibold text-orange-500 dark:text-orange-400 hover:underline text-sm"
                          >
                            {batch.batch_number}
                          </button>
                          {isRejected && (
                            <p className="text-xs text-red-600 dark:text-red-400 font-semibold mt-0.5 flex items-center gap-1">
                              <XCircle className="w-3 h-3" />
                              Rejected by Assembly
                            </p>
                          )}
                          {batch.part_number && (
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{batch.part_number}</p>
                          )}
                        </div>
                        <span
                          className={cn(
                            "text-xs font-semibold px-2 py-0.5 rounded-full tabular-nums",
                            isFull
                              ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300"
                              : "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300"
                          )}
                        >
                          {batch.blade_count}/{BATCH_MAX}
                        </span>
                      </div>

                      {!isRejected && (
                        <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden mb-3">
                          <div
                            className={cn("h-full rounded-full transition-all", isFull ? "bg-emerald-500" : "bg-orange-400")}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      )}

                      {isRejected && batch.last_event?.remarks && (
                        <p className="text-xs text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-500/20 rounded px-2 py-1 mb-3 line-clamp-2">
                          "{batch.last_event.remarks}"
                        </p>
                      )}

                      {!isRejected && (
                        <Button
                          size="sm"
                          className={cn(
                            "w-full text-xs h-8",
                            isFull
                              ? "bg-violet-600 hover:bg-violet-500 text-white"
                              : "bg-slate-600 hover:bg-slate-500 text-white"
                          )}
                          onClick={() => setSendBatchTarget(batch.batch_number)}
                        >
                          <Send className="w-3.5 h-3.5 mr-1.5" />
                          {isFull
                            ? "Send to Assembly"
                            : `Send (${remaining} blade${remaining !== 1 ? "s" : ""} remaining)`}
                        </Button>
                      )}
                    </div>
                  );
                })}
            </div>
          </div>
        )}

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 h-auto p-1 mb-5 rounded-xl shadow-sm">
            {TABS.map((tab) => (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                className="flex items-center gap-2 rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                {tab.icon}
                {tab.label}
                <span className="ml-1 rounded-full bg-slate-100 dark:bg-slate-700 data-[state=active]:bg-orange-400 px-1.5 py-0.5 text-xs tabular-nums text-slate-600 dark:text-slate-300">
                  {tabCount(tab.statuses)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          {TABS.map((tab) => (
            <TabsContent key={tab.id} value={tab.id}>
              <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                <CardContent className="p-0">
                  {!batchFilter ? (
                    <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                      <Package className="w-12 h-12 mb-3 opacity-30" />
                      <p className="font-medium">Select a batch above to view its blades</p>
                    </div>
                  ) : isLoading ? (
                    <div className="flex items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                      <Loader2 className="w-6 h-6 animate-spin mr-2" />
                      Loading queue…
                    </div>
                  ) : filtered.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                      <Inbox className="w-12 h-12 mb-3 opacity-30" />
                      <p className="font-medium">No blades in this queue</p>
                      <p className="text-sm mt-1">
                        {search ? "Try adjusting your search" : "All caught up!"}
                      </p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="bg-slate-800 dark:bg-slate-700">
                          <tr>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase w-8">
                              <input
                                type="checkbox"
                                className="rounded border-slate-500 bg-slate-700"
                                onChange={(e) =>
                                  setSelected(
                                    e.target.checked
                                      ? new Set(filtered.map((b) => b.id))
                                      : new Set()
                                  )
                                }
                                checked={
                                  filtered.length > 0 && selected.size === filtered.length
                                }
                              />
                            </th>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Serial Number
                            </th>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Melt Number
                            </th>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Status
                            </th>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Batch
                            </th>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Part Number
                            </th>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Created
                            </th>
                            <th className="text-left px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Days In
                            </th>
                            <th className="text-right px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase">
                              Actions
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200 dark:divide-slate-700/50">
                          {filtered.map((blade, rowIdx) => {
                            const daysIn = differenceInDays(
                              new Date(),
                              parseISO(blade.created_at)
                            );
                            return (
                              <tr
                                key={blade.id}
                                className={cn(
                                  "transition-colors hover:bg-blue-50 dark:hover:bg-slate-700/30",
                                  rowIdx % 2 === 0
                                    ? "bg-white dark:bg-slate-800/40"
                                    : "bg-slate-50 dark:bg-slate-800/20"
                                )}
                              >
                                <td className="px-4 py-3">
                                  <input
                                    type="checkbox"
                                    className="rounded border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-700"
                                    checked={selected.has(blade.id)}
                                    onChange={() => toggleSelect(blade.id)}
                                  />
                                </td>
                                <td className="px-4 py-3">
                                  <button
                                    onClick={() => navigate(`/blades/${blade.id}`)}
                                    className="text-orange-500 hover:text-orange-600 dark:text-orange-400 dark:hover:text-orange-300 font-mono font-medium flex items-center gap-1"
                                  >
                                    {blade.serial_number}
                                    <ExternalLink className="w-3 h-3" />
                                  </button>
                                </td>
                                <td className="px-4 py-3 text-slate-700 dark:text-slate-300 font-mono">
                                  {blade.melt_number}
                                </td>
                                <td className="px-4 py-3">
                                  <div className="flex flex-col gap-0.5">
                                    <StatusBadge status={blade.status} />
                                    {(blade.status === "CREATED" || blade.status === "OH_INSPECTION") && (
                                      <span className="text-[10px] text-amber-500 font-medium">Needs measurements</span>
                                    )}
                                    {blade.status === "MEASUREMENTS_RECORDED" && blade.batch_number && (
                                      <span className="text-[10px] text-blue-500 font-medium">Awaiting batch completion</span>
                                    )}
                                    {blade.status === "MEASUREMENTS_RECORDED" && !blade.batch_number && (
                                      <span className="text-[10px] text-violet-500 font-medium">Ready to send</span>
                                    )}
                                  </div>
                                </td>
                                <td className="px-4 py-3">
                                  {blade.batch_number ? (
                                    <button
                                      onClick={() => setBatchFilter(blade.batch_number!)}
                                      className="text-xs font-mono text-violet-600 dark:text-violet-400 hover:underline"
                                    >
                                      {blade.batch_number}
                                    </button>
                                  ) : (
                                    <span className="text-slate-400 dark:text-slate-600 text-xs">—</span>
                                  )}
                                </td>
                                <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                                  {blade.part_number ?? "—"}
                                </td>
                                <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                                  {formatDistanceToNow(parseISO(blade.created_at), {
                                    addSuffix: true,
                                  })}
                                </td>
                                <td className="px-4 py-3">
                                  <span
                                    className={cn(
                                      "font-semibold tabular-nums",
                                      daysIn > 7
                                        ? "text-red-500 dark:text-red-400"
                                        : daysIn > 3
                                        ? "text-amber-500 dark:text-amber-400"
                                        : "text-slate-700 dark:text-slate-300"
                                    )}
                                  >
                                    {daysIn}d
                                  </span>
                                </td>
                                <td className="px-4 py-3">
                                  <div className="flex items-center justify-end gap-2">
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => navigate(`/blades/${blade.id}`)}
                                      className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white h-8 px-2"
                                    >
                                      View
                                    </Button>
                                    {blade.status === "MEASUREMENTS_RECORDED" && !blade.batch_number && (
                                      <Button
                                        size="sm"
                                        onClick={() => sendToAssemblyMutation.mutate(blade.id)}
                                        disabled={sendToAssemblyMutation.isPending}
                                        className="bg-violet-600 hover:bg-violet-500 h-8 text-xs text-white"
                                      >
                                        {sendToAssemblyMutation.isPending ? (
                                          <Loader2 className="w-3 h-3 animate-spin" />
                                        ) : (
                                          <ArrowRight className="w-3 h-3" />
                                        )}
                                        Send
                                      </Button>
                                    )}
                                    {blade.status === "MEASUREMENTS_RECORDED" && blade.batch_number && (
                                      <span className="text-xs text-slate-400 dark:text-slate-500 italic">
                                        Use batch send ↑
                                      </span>
                                    )}
                                    {blade.status === "REJECTED" && (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => reopenMutation.mutate(blade.id)}
                                        disabled={reopenMutation.isPending}
                                        className="border-2 border-amber-400 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-600/20 h-8 text-xs"
                                      >
                                        <RotateCcw className="w-3 h-3" />
                                        Reopen
                                      </Button>
                                    )}
                                    {(["CREATED", "OH_INSPECTION", "MEASUREMENTS_RECORDED", "REOPENED", "ON_HOLD"] as const).includes(blade.status as any) && (
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => setConfirmDeleteId(blade.id)}
                                        className="text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 h-8 px-2"
                                        title="Delete blade"
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </Button>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          ))}
        </Tabs>
      </div>

      {/* Delete blade confirmation dialog */}
      <Dialog open={!!confirmDeleteId} onOpenChange={(open) => !open && setConfirmDeleteId(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-red-600 dark:text-red-400 flex items-center gap-2">
              <Trash2 className="w-5 h-5" />
              Delete Blade
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            This will permanently delete{" "}
            <span className="font-mono font-semibold">
              {filtered.find((b) => b.id === confirmDeleteId)?.serial_number ?? "this blade"}
            </span>{" "}
            and all its measurements, attachments, and history. This cannot be undone.
          </p>
          <DialogFooter className="gap-2">
            <Button variant="outline" size="sm" onClick={() => setConfirmDeleteId(null)} disabled={deleteMutation.isPending}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => confirmDeleteId && deleteMutation.mutate(confirmDeleteId)}
              disabled={deleteMutation.isPending}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              {deleteMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              Delete Permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Send Batch confirmation dialog */}
      <SendBatchDialog
        batchNumber={sendBatchTarget}
        bladeCount={sendBatchBladeCount}
        totalBladeCount={sendBatchTotalCount}
        onConfirm={() => sendBatchTarget && sendBatchMutation.mutate(sendBatchTarget)}
        onClose={() => setSendBatchTarget(null)}
        isLoading={sendBatchMutation.isPending}
      />
    </div>
  );
}
