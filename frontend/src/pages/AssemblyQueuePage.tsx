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
} from "lucide-react";
import { formatDistanceToNow, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import type { BladeStatus } from "@/types";
import { cn } from "@/utils/cn";
import { toast } from "sonner";

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CLS: Partial<Record<BladeStatus, string>> = {
  SENT_TO_ASSEMBLY: "bg-violet-500 text-white",
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
    <div className={cn("rounded-xl p-4 text-white shadow-md flex items-center gap-4", gradient)}>
      <div className="p-2 rounded-lg bg-white/20">{icon}</div>
      <div>
        <p className="text-white/80 text-xs font-medium">{label}</p>
        <p className="text-2xl font-bold tabular-nums">{count}</p>
      </div>
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

  // Per-batch blade fetch — only runs when a batch is selected from the filter
  const { data: batchBladesData, isLoading } = useQuery({
    queryKey: ["blades", "assembly-blades", batchFilter],
    queryFn: () => bladeService.list({ batch_number: batchFilter!, limit: 200 }),
    enabled: !!batchFilter,
    staleTime: 0,
  });

  const receiveMutation = useMutation({
    mutationFn: (batchNumber: string) => batchService.receive(batchNumber),
    onSuccess: (_, batchNumber) => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      queryClient.invalidateQueries({ queryKey: ["blades", "assembly-blades", batchNumber] });
      toast.success(`Batch ${batchNumber} marked as received — OH has been notified`);
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

  // Blade rows — only populated when a batch is selected
  const allBlades = batchFilter ? (batchBladesData?.items ?? []) : [];

  const currentTab = ASSEMBLY_TABS.find((t) => t.id === activeTab) ?? ASSEMBLY_TABS[0];

  const tabCount = (statuses: BladeStatus[]) => {
    if (batchFilter) return allBlades.filter((b) => statuses.includes(b.status)).length;
    // When no batch selected, derive from batch-level summaries
    const batchStatus = statuses.includes("SENT_TO_ASSEMBLY") ? "SENT_TO_ASSEMBLY"
      : statuses.includes("SLOT_ASSIGNED") ? "RECEIVED_BY_ASSEMBLY"
      : "ACCEPTED";
    return assemblyBatches.filter((b) => b.current_status === batchStatus).reduce((s, b) => s + b.blade_count, 0);
  };

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
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">
      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm">
        <div className="max-w-screen-xl mx-auto">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Assembly Shop Queue</h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">Balancing and slot allocation management</p>
        </div>
      </div>

      <div className="max-w-screen-xl mx-auto px-6 py-6 space-y-6">
        {/* Quick stats — vibrant gradients */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <QuickStat
            label="Incoming"
            count={incomingCount}
            icon={<Layers className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-violet-500 to-violet-600"
          />
          <QuickStat
            label="In Progress"
            count={inProgressCount}
            icon={<Wrench className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-amber-500 to-orange-500"
          />
          <QuickStat
            label="Completed"
            count={completedCount}
            icon={<CheckCircle2 className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-emerald-500 to-green-600"
          />
          <QuickStat
            label="Rejected Batches"
            count={rejectedCount}
            icon={<XCircle className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-red-500 to-rose-600"
          />
        </div>

        {/* Batch action cards — always visible */}
        {assemblyBatches.length > 0 && (
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              Batches
            </p>
            <div className="grid gap-3">
              {assemblyBatches.map((batch) => {
                const isActionable =
                  batch.current_status === "SENT_TO_ASSEMBLY" ||
                  batch.current_status === "RECEIVED_BY_ASSEMBLY" ||
                  batch.current_status === "MODIFIED";
                const isRejecting = rejectingBatch === batch.batch_number;

                return (
                  <Card
                    key={batch.batch_number}
                    className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm"
                  >
                    <CardContent className="p-4 space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-4">
                        {/* Batch info */}
                        <div className="flex items-center gap-3">
                          <Package className="w-5 h-5 text-violet-500 flex-shrink-0" />
                          <div>
                            <p className="font-semibold text-slate-900 dark:text-white font-mono">
                              {batch.batch_number}
                            </p>
                            <p className="text-xs text-slate-500 dark:text-slate-400">
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
                              className="bg-red-600 hover:bg-red-500 text-white"
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
        <div className="flex flex-wrap gap-3 items-center">
          <div className="relative min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 dark:text-slate-400" />
            <Input
              placeholder="Search serial or melt number…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-slate-50 dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <PackageSearch className="w-4 h-4 text-slate-500 dark:text-slate-400 flex-shrink-0" />
            <select
              value={batchFilter}
              onChange={(e) => setBatchFilter(e.target.value)}
              className="rounded-md border border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 min-w-[160px]"
            >
              <option value="">All Batches</option>
              {batchNumbers.map((bn) => (
                <option key={bn} value={bn}>{bn}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 h-auto p-1 mb-5 rounded-xl shadow-sm">
            {ASSEMBLY_TABS.map((tab) => (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                className="flex items-center gap-2 rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                {tab.icon}
                {tab.label}
                <span className="ml-1 rounded-full bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 text-xs tabular-nums text-slate-600 dark:text-slate-300">
                  {tabCount(tab.statuses)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          {ASSEMBLY_TABS.map((tab) => (
            <TabsContent key={tab.id} value={tab.id}>
              <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                <CardContent className="p-0">
                  {!batchFilter ? (
                    <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                      <PackageSearch className="w-12 h-12 mb-3 opacity-30" />
                      <p className="font-medium">Select a batch from the filter above to view its blades</p>
                    </div>
                  ) : isLoading ? (
                    <div className="flex items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                      <Loader2 className="w-6 h-6 animate-spin mr-2" />
                      Loading…
                    </div>
                  ) : filtered.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                      <Inbox className="w-12 h-12 mb-3 opacity-30" />
                      <p className="font-medium">No blades in this section</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="bg-slate-800 dark:bg-slate-700">
                          <tr>
                            {[
                              "Serial Number",
                              "Melt Number",
                              "Weight (g)",
                              "Static Moment (g·cm)",
                              "Status",
                              "Part Number",
                              "Received",
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
                                    className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white h-8 px-2"
                                  >
                                    View
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
