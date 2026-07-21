import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  ExternalLink,
  Layers,
  Clock,
  CheckCircle2,
  Loader2,
  Inbox,
  Wrench,
  Package,
  PackageSearch,
  PackageCheck,
  Eye,
} from "lucide-react";
import { AssemblyQueueIcon } from "@/components/common/CustomIcons";
import { formatDistanceToNow, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { assemblyService } from "@/services/assemblyService";
import type { BladeStatus } from "@/types";
import { cn } from "@/utils/cn";
import { toast } from "sonner";

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
    <div className="h-24 w-full rounded-2xl border border-white/60 dark:border-white/10 bg-white/70 dark:bg-background backdrop-blur-xl p-3.5 shadow-xl shadow-slate-200/50 dark:shadow-black/20 flex flex-col">
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
      bladeService.list({ work_order_number: batchFilter || undefined, limit: 500 }),
    staleTime: 0,
  });

  const receiveMutation = useMutation({
    mutationFn: async (workOrderNumber: string) => {
      // Update batch-level event (ignore if already received)
      try { await batchService.receive(workOrderNumber); } catch { /* already received */ }
      // Create AssemblyBatchReceipt + transition blades → ASSEMBLY_RECEIVED (ignore if already done)
      try { await assemblyService.receiveBatch(workOrderNumber, {}); } catch { /* receipt exists */ }
    },
    onSuccess: (_, workOrderNumber) => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      queryClient.invalidateQueries({ queryKey: ["blades", "assembly-blades", workOrderNumber] });
      toast.success(`Work Order ${workOrderNumber} received — blades are ready for verification`);
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to mark batch received";
      toast.error(msg);
    },
  });

  // Only batches that have reached the assembly stage
  const assemblyBatches = useMemo(
    () =>
      batches.filter((b) =>
        ["SENT_TO_ASSEMBLY", "RECEIVED_BY_ASSEMBLY", "ACCEPTED", "MODIFIED"].includes(
          b.current_status
        )
      ),
    [batches]
  );

  const workOrderNumbers = useMemo(() => {
    const nums = assemblyBatches.map((b) => b.work_order_number);
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
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
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
        <div className="shrink-0 grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
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
        </div>

        {/* Batches table */}
        {assemblyBatches.length > 0 && (
          <Card className="shrink-0 bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 overflow-hidden">
            <div className="px-4 pt-3 pb-1">
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                Batches ({assemblyBatches.length})
              </p>
            </div>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 dark:border-white/10 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                      <th className="px-4 py-2 whitespace-nowrap">Work Order</th>
                      <th className="px-4 py-2 whitespace-nowrap">Type</th>
                      <th className="px-4 py-2 whitespace-nowrap">Status</th>
                      <th className="px-4 py-2 whitespace-nowrap">Blades</th>
                      <th className="px-4 py-2 whitespace-nowrap">In Assembly</th>
                      <th className="px-4 py-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assemblyBatches.map((batch) => {
                      const isActionable =
                        batch.current_status === "SENT_TO_ASSEMBLY" ||
                        batch.current_status === "RECEIVED_BY_ASSEMBLY" ||
                        batch.current_status === "MODIFIED";

                      return (
                        <tr
                          key={batch.work_order_number}
                          className="border-b border-slate-100 dark:border-white/10 last:border-b-0 hover:bg-slate-50/80 dark:hover:bg-white/5"
                        >
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2 min-w-0">
                              <Package className="w-4 h-4 text-violet-500 flex-shrink-0" />
                              <span className="font-mono font-semibold text-sm text-slate-900 dark:text-white truncate">
                                {batch.work_order_number}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5 whitespace-nowrap">
                            <span className={cn(
                              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
                              batch.blade_type === "HPTR"
                                ? "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                                : "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                            )}>
                              {batch.blade_type ?? "LPTR"}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 whitespace-nowrap">
                            <span
                              className={cn(
                                "text-xs font-semibold",
                                batch.current_status === "SENT_TO_ASSEMBLY" && "text-violet-600 dark:text-violet-400",
                                batch.current_status === "RECEIVED_BY_ASSEMBLY" && "text-blue-600 dark:text-blue-400",
                                batch.current_status === "MODIFIED" && "text-amber-600 dark:text-amber-400",
                                batch.current_status === "ACCEPTED" && "text-emerald-600 dark:text-emerald-400",
                              )}
                            >
                              {batch.current_status_label}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300 whitespace-nowrap">
                            {batch.blade_count}
                          </td>
                          <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300 whitespace-nowrap">
                            {batch.blades_sent > 0 ? batch.blades_sent : "—"}
                          </td>
                          <td className="px-4 py-2.5">
                            {isActionable && (
                              <div className="flex flex-wrap justify-end gap-2">
                                {batch.current_status === "SENT_TO_ASSEMBLY" && (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="border-2 border-blue-500 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-500/10 text-xs h-8"
                                    disabled={receiveMutation.isPending && receiveMutation.variables === batch.work_order_number}
                                    onClick={() => receiveMutation.mutate(batch.work_order_number)}
                                  >
                                    {receiveMutation.isPending && receiveMutation.variables === batch.work_order_number ? (
                                      <Loader2 className="w-3 h-3 animate-spin mr-1" />
                                    ) : (
                                      <PackageCheck className="w-3 h-3 mr-1" />
                                    )}
                                    Mark Received
                                  </Button>
                                )}
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="border-2 border-emerald-500 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 text-xs h-8"
                                  onClick={() => navigate(`/batches/${batch.work_order_number}/accept`)}
                                >
                                  <CheckCircle2 className="w-3 h-3 mr-1" />
                                  Accept
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="border-2 border-amber-500 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-500/10 text-xs h-8"
                                  onClick={() => navigate(`/batches/${batch.work_order_number}/modify`)}
                                >
                                  <Wrench className="w-3 h-3 mr-1" />
                                  Modify
                                </Button>
                              </div>
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

        {/* Search + Batch filter (for blade table) */}
        <div className="shrink-0 flex flex-wrap gap-3 items-center">
          <div className="relative min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 dark:text-slate-400" />
            <Input
              placeholder="Search serial or melt number…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 shadow-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            <PackageSearch className="w-4 h-4 text-slate-500 dark:text-slate-400 flex-shrink-0" />
            <select
              value={batchFilter}
              onChange={(e) => setBatchFilter(e.target.value)}
              className="rounded-md border border-white/60 dark:border-white/10 bg-white/70 dark:bg-background backdrop-blur-xl text-slate-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 min-w-[160px] shadow-sm"
            >
              <option value="">All Batches</option>
              {workOrderNumbers.map((bn) => (
                <option key={bn} value={bn}>{bn}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 min-h-0 flex flex-col">
          <TabsList className="shrink-0 flex-wrap bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 h-auto p-1 mb-3 rounded-xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 self-start">
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
                <span className="ml-1 rounded-full bg-slate-100 dark:bg-background group-data-[state=active]:bg-white/20 px-1.5 py-0.5 text-xs tabular-nums text-slate-600 dark:text-slate-300 group-data-[state=active]:text-white border border-transparent group-data-[state=active]:border-white/10">
                  {tabCount(tab.statuses)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          {ASSEMBLY_TABS.map((tab) => (
            <TabsContent key={tab.id} value={tab.id} className="flex-1 min-h-0 flex flex-col mt-0 data-[state=inactive]:hidden">
              <Card className="flex-1 min-h-0 flex flex-col bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 overflow-hidden">
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
                        <thead className="bg-slate-800 dark:bg-background">
                          <tr>
                            {[
                              "Serial Number",
                              "Melt Number",
                              "Weight (g)",
                              "Static Moment (g·cm)",
                              "Status",
                              "Type",
                              "Part Number",
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
                                rowIdx % 2 === 0 ? "bg-white dark:bg-background" : "bg-slate-50 dark:bg-background"
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
                              <td className="px-4 py-3">
                                <span className={cn(
                                  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
                                  blade.blade_type === "HPTR"
                                    ? "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                                    : "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                                )}>
                                  {blade.blade_type ?? "LPTR"}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{blade.part_number}</td>
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

    </div>
  );
}
