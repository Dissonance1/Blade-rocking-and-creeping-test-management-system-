import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  ExternalLink,
  Layers,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Inbox,
  Wrench,
  Package,
  PackageSearch,
  PackageCheck,
  Eye,
  Activity,
  AlertTriangle,
} from "lucide-react";
import { AssemblyQueueIcon } from "@/components/common/CustomIcons";
import { formatDistanceToNow, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { assemblyService } from "@/services/assemblyService";
import type { BladeStatus } from "@/types";
import { cn } from "@/utils/cn";
import { toast } from "sonner";
import Footer from "@/layouts/components/Navbar/Footer";

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CLS: Partial<Record<BladeStatus, string>> = {
  SENT_TO_ASSEMBLY: "bg-violet-500 text-white",
  ASSEMBLY_RECEIVED: "bg-blue-500 text-white",
  ASSEMBLY_VERIFIED: "bg-emerald-600 text-white",
  SLOT_ASSIGNED: "bg-cyan-500 text-white",
  BALANCING_IN_PROGRESS: "bg-orange-500 text-white",
  BALANCING_COMPLETED: "bg-emerald-500 text-white",
  RETURNED_TO_OH: "bg-amber-500 text-white",
};

function StatusBadge({ status }: { status: BladeStatus }) {
  const cls = STATUS_CLS[status] ?? "bg-slate-500 text-white";
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

// ─── Stat card ────────────────────────────────────────────────────────────────

function QuickStat({
  label,
  count,
  icon,
  gradient,
}: {
  label: string;
  count: number;
  icon: React.ReactNode;
  gradient: string;
}) {
  return (
    <div className="h-24 w-full rounded-2xl border border-white/60 dark:border-white/10 bg-white/70 dark:bg-black/40 backdrop-blur-xl p-3.5 shadow-xl shadow-slate-200/50 dark:shadow-black/20 flex flex-col">
      <div className="flex items-center gap-2.5 min-w-0">
        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center shadow-lg text-white shrink-0", gradient)}>
          {icon}
        </div>
        <p className="text-sm font-bold text-slate-900 dark:text-white truncate">{label}</p>
      </div>
      <p className="text-2xl font-semibold tabular-nums tracking-tight mt-auto text-slate-900 dark:text-white">{count}</p>
    </div>
  );
}

// ─── (individual blade dialogs removed — actions are batch-level only) ────────

const ASSEMBLY_TABS = [
  {
    id: "incoming",
    label: "Incoming",
    icon: <Layers className="w-4 h-4" />,
    statuses: ["SENT_TO_ASSEMBLY"] as BladeStatus[],
  },
  {
    id: "verifying",
    label: "Verifying",
    icon: <Wrench className="w-4 h-4" />,
    statuses: ["ASSEMBLY_RECEIVED", "ASSEMBLY_VERIFIED"] as BladeStatus[],
  },
  {
    id: "in_progress",
    label: "In Progress",
    icon: <Clock className="w-4 h-4" />,
    statuses: ["SLOT_ASSIGNED", "BALANCING_IN_PROGRESS"] as BladeStatus[],
  },
  {
    id: "completed",
    label: "Completed",
    icon: <CheckCircle2 className="w-4 h-4" />,
    statuses: ["BALANCING_COMPLETED"] as BladeStatus[],
  },
] as const;

// ─── Main component ───────────────────────────────────────────────────────────

export default function AssemblyQueuePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("incoming");
  const [search, setSearch] = useState("");
  const [batchFilter, setBatchFilter] = useState<string>("");
  const [rejectingBatch, setRejectingBatch] = useState<string | null>(null);
  const [batchRemarks, setBatchRemarks] = useState("");

  // Batch list — drives cards, counts, and dropdown
  const { data: batches = [] } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  // Blade fetch — when a batch is selected, scoped to that batch; otherwise all assembly blades
  const { data: batchBladesData, isLoading } = useQuery({
    queryKey: ["blades", "assembly-blades", batchFilter],
    queryFn: () =>
      bladeService.list({ batch_number: batchFilter || undefined, limit: 500 }),
    staleTime: 0,
  });

  const receiveMutation = useMutation({
    mutationFn: async (batchNumber: string) => {
      // Update batch-level event (ignore if already received)
      try { await batchService.receive(batchNumber); } catch { /* already received */ }
      // Create AssemblyBatchReceipt + transition blades → ASSEMBLY_RECEIVED (ignore if already done)
      try { await assemblyService.receiveBatch(batchNumber, {}); } catch { /* receipt exists */ }
    },
    onSuccess: (_, batchNumber) => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      queryClient.invalidateQueries({ queryKey: ["blades", "assembly-blades", batchNumber] });
      toast.success(`Batch ${batchNumber} received — blades are ready for verification`);
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to mark batch received";
      toast.error(msg);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ batchNumber, remarks }: { batchNumber: string; remarks: string }) =>
      batchService.reject(batchNumber, remarks),
    onSuccess: (_, { batchNumber }) => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      queryClient.invalidateQueries({ queryKey: ["blades", "assembly-blades", batchNumber] });
      toast.success(`Batch ${batchNumber} rejected`);
      setRejectingBatch(null);
      setBatchRemarks("");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to reject batch";
      toast.error(msg);
    },
  });

  // Only batches that have reached the assembly stage
  const assemblyBatches = useMemo(
    () =>
      batches.filter((b) =>
        ["SENT_TO_ASSEMBLY", "RECEIVED_BY_ASSEMBLY", "ACCEPTED", "REJECTED", "MODIFIED"].includes(
          b.current_status
        )
      ),
    [batches]
  );

  const batchNumbers = useMemo(() => {
    const nums = assemblyBatches.map((b) => b.batch_number);
    return [...new Set(nums)].sort();
  }, [assemblyBatches]);

  // Counts derived from batch summaries — no blade-list dependency, no pagination limits
  const incomingCount = useMemo(
    () => assemblyBatches.filter((b) => b.current_status === "SENT_TO_ASSEMBLY").reduce((s, b) => s + b.blade_count, 0),
    [assemblyBatches]
  );
  const inProgressCount = useMemo(
    () => assemblyBatches.filter((b) => ["RECEIVED_BY_ASSEMBLY", "MODIFIED"].includes(b.current_status)).reduce((s, b) => s + b.blade_count, 0),
    [assemblyBatches]
  );
  const completedCount = useMemo(
    () => assemblyBatches.filter((b) => b.current_status === "ACCEPTED").reduce((s, b) => s + b.blade_count, 0),
    [assemblyBatches]
  );
  const rejectedCount = useMemo(
    () => assemblyBatches.filter((b) => b.current_status === "REJECTED").length,
    [assemblyBatches]
  );

  const allBlades = batchBladesData?.items ?? [];

  const currentTab = ASSEMBLY_TABS.find((t) => t.id === activeTab) ?? ASSEMBLY_TABS[0];

  const tabCount = (statuses: BladeStatus[]) =>
    allBlades.filter((b) => statuses.includes(b.status)).length;

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return allBlades
      .filter((b) => currentTab.statuses.includes(b.status))
      .filter(
        (b) =>
          !q ||
          b.serial_number.toLowerCase().includes(q) ||
          b.melt_number.toLowerCase().includes(q)
      );
  }, [allBlades, activeTab, search, currentTab.statuses]);

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-black dark:from-black dark:via-black dark:to-black text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-black/40 px-4 sm:px-6 py-2.5">
        <div className="w-full max-w-[1600px] mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <AssemblyQueueIcon className="w-5 h-5 text-orange-500 shrink-0" />
              Assembly Shop Queue
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight">
              Balancing and slot allocation management
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 w-full max-w-[1600px] mx-auto px-4 sm:px-6 py-5 flex flex-col gap-5">
        {/* Quick stats — vibrant gradients */}
        <div className="shrink-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <QuickStat
            label="Incoming"
            count={incomingCount}
            icon={<Layers className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-violet-400 to-violet-600 shadow-violet-500/30"
          />
          <QuickStat
            label="In Progress"
            count={inProgressCount}
            icon={<Wrench className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-amber-400 to-orange-600 shadow-orange-500/30"
          />
          <QuickStat
            label="Completed"
            count={completedCount}
            icon={<CheckCircle2 className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-emerald-400 to-emerald-600 shadow-emerald-500/30"
          />
          <QuickStat
            label="Rejected Batches"
            count={rejectedCount}
            icon={<XCircle className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-red-400 to-red-600 shadow-red-500/30"
          />
        </div>

        {/* Batch action cards — always visible */}
        {assemblyBatches.length > 0 && (
          <div className="shrink-0 flex flex-col">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500 mb-2 shrink-0">
              Batches
            </p>
            <div className="grid gap-3 pr-2 pb-1">
              {assemblyBatches.map((batch) => {
                const isActionable =
                  batch.current_status === "SENT_TO_ASSEMBLY" ||
                  batch.current_status === "RECEIVED_BY_ASSEMBLY" ||
                  batch.current_status === "MODIFIED";
                const isRejecting = rejectingBatch === batch.batch_number;

                return (
                  <Card
                    key={batch.batch_number}
                    className="bg-white/70 dark:bg-black/40 backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20"
                  >
                    <CardContent className="p-4 space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-4">
                        {/* Batch info */}
                        <div className="flex items-center gap-3 min-w-0">
                          <Package className="w-5 h-5 text-violet-500 flex-shrink-0" />
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-900 dark:text-white font-mono truncate">
                              {batch.batch_number}
                            </p>
                            <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                              <span
                                className={cn(
                                  "font-medium",
                                  batch.current_status === "SENT_TO_ASSEMBLY" && "text-violet-600 dark:text-violet-400",
                                  batch.current_status === "RECEIVED_BY_ASSEMBLY" && "text-blue-600 dark:text-blue-400",
                                  batch.current_status === "MODIFIED" && "text-amber-600 dark:text-amber-400",
                                  batch.current_status === "ACCEPTED" && "text-emerald-600 dark:text-emerald-400",
                                  batch.current_status === "REJECTED" && "text-red-600 dark:text-red-400",
                                )}
                              >
                                {batch.current_status_label}
                              </span>
                              {" · "}{batch.blade_count} blades
                              {batch.blades_sent > 0 && ` · ${batch.blades_sent} in Assembly`}
                            </p>
                          </div>
                        </div>

                        {/* Action buttons */}
                        {isActionable && !isRejecting && (
                          <div className="flex flex-wrap gap-2">
                            {batch.current_status === "SENT_TO_ASSEMBLY" && (
                              <Button
                                size="sm"
                                variant="outline"
                                className="border-2 border-blue-500 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-500/10 text-xs h-8"
                                disabled={receiveMutation.isPending && receiveMutation.variables === batch.batch_number}
                                onClick={() => receiveMutation.mutate(batch.batch_number)}
                              >
                                {receiveMutation.isPending && receiveMutation.variables === batch.batch_number ? (
                                  <Loader2 className="w-3 h-3 animate-spin mr-1" />
                                ) : (
                                  <PackageCheck className="w-3 h-3 mr-1" />
                                )}
                                Mark Received
                              </Button>
                            )}
                            {batch.current_status === "RECEIVED_BY_ASSEMBLY" && (
                              <Button
                                size="sm"
                                className="bg-blue-600 hover:bg-blue-500 text-white text-xs h-8"
                                onClick={() => navigate(`/assembly/verify/${batch.batch_number}`)}
                              >
                                <PackageCheck className="w-3 h-3 mr-1" />
                                Verify Blades
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="outline"
                              className="border-2 border-emerald-500 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 text-xs h-8"
                              onClick={() => navigate(`/batches/${batch.batch_number}/accept`)}
                            >
                              <CheckCircle2 className="w-3 h-3 mr-1" />
                              Accept
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="border-2 border-amber-500 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-500/10 text-xs h-8"
                              onClick={() => navigate(`/batches/${batch.batch_number}/modify`)}
                            >
                              <Wrench className="w-3 h-3 mr-1" />
                              Modify
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="border-2 border-red-500 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 text-xs h-8"
                              onClick={() => { setRejectingBatch(batch.batch_number); setBatchRemarks(""); }}
                            >
                              <XCircle className="w-3 h-3 mr-1" />
                              Reject
                            </Button>
                          </div>
                        )}
                      </div>

                      {/* Inline reject form */}
                      {isRejecting && (
                        <div className="pt-3 border-t border-slate-200 dark:border-slate-700 space-y-3">
                          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                            Reject Batch —{" "}
                            <span className="font-mono text-orange-500">{batch.batch_number}</span>
                          </p>
                          <Textarea
                            value={batchRemarks}
                            onChange={(e) => setBatchRemarks(e.target.value)}
                            placeholder="Reason required…"
                            className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white min-h-[60px] text-sm"
                          />
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              onClick={() =>
                                rejectMutation.mutate({ batchNumber: batch.batch_number, remarks: batchRemarks.trim() })
                              }
                              disabled={rejectMutation.isPending || !batchRemarks.trim()}
                              className={cn(
                                "text-white",
                                (!batchRemarks.trim() || rejectMutation.isPending)
                                  ? "bg-slate-400 dark:bg-slate-600 cursor-not-allowed opacity-100"
                                  : "bg-red-600 hover:bg-red-500"
                              )}
                            >
                              {rejectMutation.isPending && (
                                <Loader2 className="w-3 h-3 animate-spin mr-1.5" />
                              )}
                              Confirm Rejection
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => { setRejectingBatch(null); setBatchRemarks(""); }}
                              className="text-slate-500 hover:text-slate-700"
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        )}

        {/* Search + Batch filter (for blade table) */}
        <div className="shrink-0 flex flex-wrap gap-3 items-center">
          <div className="relative min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 dark:text-slate-400" />
            <Input
              placeholder="Search serial or melt number…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-white/70 dark:bg-black/40 backdrop-blur-xl border border-white/60 dark:border-white/10 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 shadow-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            <PackageSearch className="w-4 h-4 text-slate-500 dark:text-slate-400 flex-shrink-0" />
            <select
              value={batchFilter}
              onChange={(e) => setBatchFilter(e.target.value)}
              className="rounded-md border border-white/60 dark:border-white/10 bg-white/70 dark:bg-black/40 backdrop-blur-xl text-slate-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 min-w-[160px] shadow-sm"
            >
              <option value="">All Batches</option>
              {batchNumbers.map((bn) => (
                <option key={bn} value={bn}>{bn}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 min-h-0 flex flex-col">
          <TabsList className="shrink-0 flex-wrap bg-white/70 dark:bg-black/40 backdrop-blur-xl border border-white/60 dark:border-white/10 h-auto p-1 mb-3 rounded-xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 self-start">
            {ASSEMBLY_TABS.map((tab) => (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                className="group flex items-center gap-2 rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                <div className="text-slate-500 dark:text-slate-400 group-data-[state=active]:text-white">
                  {tab.icon}
                </div>
                <span className="font-medium group-data-[state=active]:text-white">{tab.label}</span>
                <span className="ml-1 rounded-full bg-slate-100 dark:bg-slate-700 group-data-[state=active]:bg-white/20 px-1.5 py-0.5 text-xs tabular-nums text-slate-600 dark:text-slate-300 group-data-[state=active]:text-white border border-transparent group-data-[state=active]:border-white/10">
                  {tabCount(tab.statuses)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          {ASSEMBLY_TABS.map((tab) => (
            <TabsContent key={tab.id} value={tab.id} className="flex-1 min-h-0 flex flex-col mt-0 data-[state=inactive]:hidden">
              <Card className="flex-1 min-h-0 flex flex-col bg-white/70 dark:bg-black/40 backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 overflow-hidden">
                <CardContent className="flex-1 min-h-0 overflow-y-auto p-0">
                  {isLoading ? (
                    <div className="flex items-center justify-center py-16 text-slate-400 dark:text-slate-500 h-full">
                      <Loader2 className="w-6 h-6 animate-spin mr-2" />
                      Loading…
                    </div>
                  ) : filtered.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 h-full">
                      <Inbox className="w-12 h-12 mb-3 opacity-30" />
                      <p className="font-medium">No blades in this section</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm whitespace-nowrap">
                        <thead className="bg-slate-800 dark:bg-slate-700">
                          <tr>
                            {[
                              "Serial Number",
                              "Melt Number",
                              "Weight (g)",
                              "Static Moment (g·cm)",
                              "Status",
                              "Part Number",
                              "Nomenclature",
                              "Received",
                              "Preview",
                            ].map((h) => (
                              <th
                                key={h}
                                className={cn(
                                  "px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase text-left",
                                  h === "Preview" && "text-right"
                                )}
                              >
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200 dark:divide-slate-700/50">
                          {filtered.map((blade, rowIdx) => (
                            <tr
                              key={blade.id}
                              className={cn(
                                "transition-colors hover:bg-blue-50 dark:hover:bg-slate-700/30",
                                rowIdx % 2 === 0 ? "bg-white dark:bg-slate-800/40" : "bg-slate-50 dark:bg-slate-800/20"
                              )}
                            >
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
                              <td className="px-4 py-3 font-mono tabular-nums text-slate-700 dark:text-slate-200 font-medium">
                                {blade.weight_grams != null ? blade.weight_grams.toFixed(2) : "—"}
                              </td>
                              <td className="px-4 py-3 font-mono tabular-nums text-slate-700 dark:text-slate-200 font-medium">
                                {blade.static_moment_gcm != null ? blade.static_moment_gcm.toFixed(2) : "—"}
                              </td>
                              <td className="px-4 py-3">
                                <StatusBadge status={blade.status} />
                              </td>
                              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{blade.part_number}</td>
                              <td className="px-4 py-3 text-slate-500 dark:text-slate-400 max-w-[160px] truncate">
                                {blade.nomenclature}
                              </td>
                              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                                {formatDistanceToNow(parseISO(blade.updated_at), {
                                  addSuffix: true,
                                })}
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex items-center justify-end gap-2">
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => navigate(`/blades/${blade.id}`)}
                                    className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white h-8 px-2 flex items-center gap-1.5"
                                  >
                                    <Eye className="w-4 h-4" />
                                    <span>View</span>
                                  </Button>
                                  {(blade.status === "SLOT_ASSIGNED" ||
                                    blade.status === "BALANCING_IN_PROGRESS") && (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => navigate(`/assembly/slots`)}
                                      className="border-2 border-orange-400 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-600/20 h-8 text-xs"
                                    >
                                      <Wrench className="w-3 h-3" />
                                      Update Balancing
                                    </Button>
                                  )}
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
            </TabsContent>
          ))}
        </Tabs>
      </div>

      <div className="shrink-0 px-4 sm:px-6 pb-3">
        <div className="w-full">
          <Footer />
        </div>
      </div>

    </div>
  );
}
