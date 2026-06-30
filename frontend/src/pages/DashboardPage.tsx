import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Layers,
  Clock,
  CheckCircle2,
  XCircle,
  Plus,
  ArrowRight,
  RefreshCw,
  Activity,
  Wrench,
  Hash,
  ChevronDown,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ChevronRight,
  Weight,
  Search,
} from "lucide-react";
import { formatDistanceToNow, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import { workflowService } from "@/services/workflowService";
import api from "@/services/api";
import type { BladeStatus, DashboardStats, BladeListItem } from "@/types";
import { cn } from "@/utils/cn";

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CFG: Record<BladeStatus, { label: string; color: string }> = {
  CREATED:               { label: "Created",               color: "bg-indigo-500 text-white" },
  OH_INSPECTION:         { label: "OH Inspection",         color: "bg-amber-500 text-white" },
  MEASUREMENTS_RECORDED: { label: "Measurements",          color: "bg-blue-500 text-white" },
  SENT_TO_ASSEMBLY:      { label: "Sent to Assembly",      color: "bg-violet-500 text-white" },
  ASSEMBLY_RECEIVED:     { label: "Received at Assembly",  color: "bg-sky-500 text-white" },
  ASSEMBLY_VERIFIED:     { label: "Assembly Verified",     color: "bg-emerald-600 text-white" },
  SLOT_ASSIGNED:         { label: "Slot Assigned",         color: "bg-cyan-500 text-white" },
  BALANCING_IN_PROGRESS: { label: "Balancing",             color: "bg-orange-500 text-white" },
  BALANCING_COMPLETED:   { label: "Balanced",              color: "bg-emerald-500 text-white" },
  RETURNED_TO_OH:        { label: "Returned to OH",        color: "bg-amber-500 text-white" },
  FINAL_VERIFICATION:    { label: "Final Verify",          color: "bg-sky-500 text-white" },
  COMPLETED:             { label: "Completed",             color: "bg-green-600 text-white" },
  REJECTED:              { label: "Rejected",              color: "bg-red-500 text-white" },
  ON_HOLD:               { label: "On Hold",               color: "bg-slate-500 text-white" },
  REOPENED:              { label: "Reopened",              color: "bg-purple-500 text-white" },
};

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ title, value, icon, gradient, shadow }: {
  title: string; value: number; icon: React.ReactNode;
  gradient: string; shadow: string;
}) {
  return (
    <div className={cn("rounded-xl p-5 text-white shadow-lg", gradient, shadow)}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-white/80 text-sm font-medium">{title}</p>
          <p className="text-3xl font-bold mt-1">{value}</p>
        </div>
        <div className="w-12 h-12 rounded-xl bg-white/20 flex items-center justify-center">
          {icon}
        </div>
      </div>
    </div>
  );
}

// ─── Sort config ──────────────────────────────────────────────────────────────

type SortKey = "serial_number" | "weight_grams" | "static_moment" | "status" | "created_at";
type SortDir = "asc" | "desc";

// BladeListItem already has weight_grams, static_moment_gcm, work_order_number, engine_number
type BladeSortable = BladeListItem;

interface WorkOrderSummary {
  work_order_number: string;
  shop_order_number: string | null;
  engine_number: string | null;
  part_number: string;
  nomenclature: string;
  blade_count: number;
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const navigate = useNavigate();
  const [selectedWO, setSelectedWO] = useState<string | null>(null);
  const [showWODropdown, setShowWODropdown] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("serial_number");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<BladeStatus | "ALL">("ALL");

  // ── Queries ──────────────────────────────────────────────────────────────
  const { data: stats, dataUpdatedAt, refetch, isFetching } = useQuery<DashboardStats>({
    queryKey: ["dashboard-stats"],
    queryFn: workflowService.getDashboardStats,
    refetchInterval: 30_000,
  });

  const { data: workOrders = [] } = useQuery<WorkOrderSummary[]>({
    queryKey: ["dashboard-work-orders"],
    queryFn: async () => {
      const { data } = await api.get("/workflows/dashboard/work-orders");
      return data;
    },
    refetchInterval: 60_000,
  });

  // Client-side pagination state
  const [perPage, setPerPage] = useState<number>(50);
  const [currentPage, setCurrentPage] = useState(1);

  // Fetch blades — status filter applied server-side, limit=1000 (backend max)
  const { data: bladesData, isLoading: loadingBlades } = useQuery<{
    items: BladeSortable[];
    total: number;
  }>({
    queryKey: ["dashboard-blades-all", statusFilter],
    queryFn: async () => {
      const params = statusFilter !== "ALL"
        ? `status=${statusFilter}&limit=1000&page=1`
        : `limit=1000&page=1`;
      const { data } = await api.get(`/blades/?${params}`);
      return data as { items: BladeSortable[]; total: number };
    },
    refetchInterval: 30_000,
  });

  const allBladesTotal = bladesData?.total ?? 0;

  const activeWO: WorkOrderSummary | null =
    workOrders.find((w) => w.work_order_number === selectedWO) ??
    workOrders[0] ?? null;

  // ── Sort + filter + paginate — all client-side ───────────────────────────
  const allBlades: BladeSortable[] = bladesData?.items ?? [];

  // Step 1: filter
  const filtered = allBlades.filter((b) => {
    const q = search.toLowerCase();
    const matchSearch =
      !q ||
      b.serial_number.toLowerCase().includes(q) ||
      (b.melt_number ?? "").toLowerCase().includes(q) ||
      (b.work_order_number ?? "").toLowerCase().includes(q) ||
      (b.engine_number ?? "").toLowerCase().includes(q);
    const matchStatus = statusFilter === "ALL" || b.status === statusFilter;
    return matchSearch && matchStatus;
  });

  // Step 2: sort
  const sortedAll = [...filtered].sort((a, b) => {
    let cmp = 0;
    if (sortKey === "serial_number") cmp = a.serial_number.localeCompare(b.serial_number);
    else if (sortKey === "weight_grams") cmp = ((a.weight_grams ?? 0) - (b.weight_grams ?? 0));
    else if (sortKey === "static_moment") cmp = ((a.static_moment_gcm ?? 0) - (b.static_moment_gcm ?? 0));
    else if (sortKey === "status") cmp = a.status.localeCompare(b.status);
    else if (sortKey === "created_at") cmp = a.created_at.localeCompare(b.created_at);
    return sortDir === "asc" ? cmp : -cmp;
  });

  // Step 3: client-side paginate
  const totalFiltered = sortedAll.length;
  const totalPages = Math.max(1, Math.ceil(totalFiltered / perPage));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const pageStart = (safeCurrentPage - 1) * perPage;
  const sorted = sortedAll.slice(pageStart, pageStart + perPage);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  }

  function SortIcon({ k }: { k: SortKey }) {
    if (sortKey !== k) return <ArrowUpDown className="w-3.5 h-3.5 text-slate-400" />;
    return sortDir === "asc"
      ? <ArrowUp className="w-3.5 h-3.5 text-orange-500" />
      : <ArrowDown className="w-3.5 h-3.5 text-orange-500" />;
  }

  const uniqueStatuses = Array.from(new Set(allBlades.map((b) => b.status))).sort();

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">

      {/* ── Sticky header ───────────────────────────────────────────────── */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 sticky top-0 z-10 shadow-sm">
        <div className="flex items-center justify-between max-w-screen-2xl mx-auto">
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2 text-slate-900 dark:text-white">
              <Activity className="w-5 h-5 text-orange-500" />
              Operations Dashboard
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              {dataUpdatedAt
                ? `Last updated ${formatDistanceToNow(dataUpdatedAt, { addSuffix: true })}`
                : "Loading…"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 gap-1.5">
              <RefreshCw className={cn("w-3.5 h-3.5", isFetching && "animate-spin")} />
              Refresh
            </Button>
            <Button size="sm" onClick={() => navigate("/blades/new")}
              className="bg-orange-500 hover:bg-orange-600 text-white gap-1.5">
              <Plus className="w-3.5 h-3.5" /> New Blade Entry
            </Button>
            <Button variant="outline" size="sm" onClick={() => navigate("/assembly-queue")}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 gap-1.5">
              Assembly Queue <ArrowRight className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </div>

      <div className="max-w-screen-2xl mx-auto px-6 py-6 space-y-5">

        {/* ── Work Order / Engine Summary ─────────────────────────────────── */}
        {workOrders.length > 0 && (
          <div className="bg-white dark:bg-slate-800/60 rounded-xl border border-slate-200 dark:border-slate-700/60 shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 bg-slate-800 dark:bg-slate-900">
              <div className="flex items-center gap-2">
                <Wrench className="w-4 h-4 text-orange-400" />
                <span className="text-white text-sm font-semibold tracking-wide uppercase">Active Work Order</span>
              </div>
              <div className="relative">
                <button onClick={() => setShowWODropdown((v) => !v)}
                  className="flex items-center gap-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-xs px-3 py-1.5 transition-colors">
                  <span className="font-mono">{activeWO?.work_order_number ?? "Select WO"}</span>
                  <ChevronDown className="w-3 h-3" />
                </button>
                {showWODropdown && (
                  <div className="absolute right-0 top-full mt-1 z-20 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-xl min-w-[220px] max-h-60 overflow-y-auto">
                    {workOrders.map((wo) => (
                      <button key={wo.work_order_number + wo.engine_number}
                        onClick={() => { setSelectedWO(wo.work_order_number); setShowWODropdown(false); }}
                        className={cn("w-full text-left px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors",
                          wo.work_order_number === activeWO?.work_order_number
                            ? "bg-orange-50 dark:bg-orange-500/10 text-orange-600 dark:text-orange-400 font-medium"
                            : "text-slate-700 dark:text-slate-300")}>
                        <span className="font-mono text-xs">{wo.work_order_number}</span>
                        <span className="block text-xs text-slate-400 mt-0.5">{wo.engine_number} · {wo.blade_count} blades</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {activeWO && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 divide-x divide-y sm:divide-y-0 divide-slate-100 dark:divide-slate-700/50">
                {[
                  { icon: <Hash className="w-3.5 h-3.5" />, label: "Work Order",   value: activeWO.work_order_number, mono: true },
                  { icon: <Hash className="w-3.5 h-3.5" />, label: "Shop Order",   value: activeWO.shop_order_number,  mono: true },
                  { icon: <Wrench className="w-3.5 h-3.5"/>, label: "Engine No.",  value: activeWO.engine_number,      mono: true },
                  { icon: <Layers className="w-3.5 h-3.5"/>, label: "Part Number", value: activeWO.part_number,        mono: true },
                  { icon: <Activity className="w-3.5 h-3.5"/>,label:"Nomenclature",value: activeWO.nomenclature,       mono: false },
                ].map(({ icon, label, value, mono }) => (
                  <div key={label} className="px-4 py-3">
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="text-slate-400 dark:text-slate-500">{icon}</span>
                      <span className="text-slate-400 dark:text-slate-500 text-[10px] font-semibold uppercase tracking-widest">{label}</span>
                    </div>
                    <p className={cn("text-slate-900 dark:text-white font-semibold text-sm truncate", mono && "font-mono")}>
                      {value ?? "—"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Stat cards ──────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          <StatCard title="Active Blades"  value={stats?.total_active ?? 0}
            icon={<Layers className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-blue-500 to-blue-600"
            shadow="shadow-blue-200 dark:shadow-blue-900/50" />
          <StatCard title="In Progress"
            value={stats ? Object.values(stats.by_status ?? {}).reduce((a,b)=>a+(b??0),0)-(stats.total_completed??0)-(stats.total_rejected??0) : 0}
            icon={<Clock className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-amber-500 to-orange-500"
            shadow="shadow-amber-200 dark:shadow-amber-900/50" />
          <StatCard title="Completed"     value={stats?.total_completed ?? 0}
            icon={<CheckCircle2 className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-emerald-500 to-green-600"
            shadow="shadow-emerald-200 dark:shadow-emerald-900/50" />
          <StatCard title="Rejected"      value={stats?.total_rejected ?? 0}
            icon={<XCircle className="w-5 h-5 text-white" />}
            gradient="bg-gradient-to-br from-red-500 to-rose-600"
            shadow="shadow-red-200 dark:shadow-red-900/50" />
        </div>

        {/* ── Unbalanced alert ─────────────────────────────────────────────── */}
        {((stats?.total_unbalanced ?? 0) > 0) && (
          <div className="rounded-xl bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 p-4">
            <div className="flex items-start gap-3">
              <XCircle className="w-5 h-5 text-red-500 dark:text-red-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-red-700 dark:text-red-300 text-sm font-semibold">
                  {stats?.total_unbalanced} Unbalanced Slot{(stats?.total_unbalanced ?? 0) !== 1 ? "s" : ""} — Assembly Action Required
                </p>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {(stats?.unbalanced_slots ?? []).slice(0, 10).map((s) => (
                    <span key={s.slot_number} className="rounded-md bg-red-100 dark:bg-red-500/20 border border-red-300 dark:border-red-500/40 px-2 py-0.5 text-xs font-mono font-semibold text-red-700 dark:text-red-300">
                      Slot {s.slot_number}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Blade Table ──────────────────────────────────────────────────── */}
        <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
          <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                <Weight className="w-4 h-4 text-orange-500" />
                All Blades
                <span className="ml-1 text-sm font-normal text-slate-400 dark:text-slate-500">
                  ({sorted.length} of {allBlades.length})
                </span>
              </CardTitle>

              <div className="flex items-center gap-2 flex-wrap">
                {/* Search */}
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                  <Input value={search} onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search serial / melt / WO…"
                    className="pl-8 h-8 text-xs w-52 bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600" />
                </div>

                {/* Status filter */}
                <select value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as BladeStatus | "ALL")}
                  className="h-8 text-xs rounded-lg border-2 border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50 text-slate-700 dark:text-slate-300 px-2 pr-7 focus:outline-none focus:border-orange-400">
                  <option value="ALL">All Statuses</option>
                  {uniqueStatuses.map((s) => (
                    <option key={s} value={s}>{STATUS_CFG[s as BladeStatus]?.label ?? s}</option>
                  ))}
                </select>
              </div>
            </div>
          </CardHeader>

          <CardContent className="p-0">
            {loadingBlades ? (
              <div className="flex items-center justify-center py-16 text-slate-400 dark:text-slate-500 text-sm gap-2">
                <RefreshCw className="w-4 h-4 animate-spin" /> Loading blades…
              </div>
            ) : sorted.length === 0 ? (
              <div className="text-center py-16 text-slate-400 dark:text-slate-500 text-sm">
                No blades match your filter
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[900px]">
                  <thead>
                    <tr className="bg-slate-800 dark:bg-slate-700">
                      {[
                        { key: "serial_number" as SortKey, label: "Serial No.", width: "w-36" },
                        { key: null, label: "Melt No.", width: "w-32" },
                        { key: "weight_grams" as SortKey, label: "Weight (g)", width: "w-28" },
                        { key: "static_moment" as SortKey, label: "Static Moment", width: "w-32" },
                        { key: "status" as SortKey, label: "Status", width: "w-36" },
                        { key: null, label: "Work Order", width: "w-36" },
                        { key: null, label: "Engine No.", width: "w-36" },
                        { key: null, label: "Part No.", width: "w-32" },
                        { key: "created_at" as SortKey, label: "Entered", width: "w-28" },
                        { key: null, label: "", width: "w-8" },
                      ].map(({ key, label, width }) => (
                        <th key={label}
                          className={cn("px-4 py-3 text-left text-slate-100 font-semibold tracking-wide text-xs uppercase", width,
                            key && "cursor-pointer hover:text-orange-300 transition-colors select-none"
                          )}
                          onClick={() => key && toggleSort(key)}>
                          <span className="flex items-center gap-1.5">
                            {label}
                            {key && <SortIcon k={key} />}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-700/40">
                    {sorted.map((blade, idx) => {
                      const cfg = STATUS_CFG[blade.status];
                      const isEven = idx % 2 === 0;
                      return (
                        <tr key={blade.id}
                          onClick={() => navigate(`/blades/${blade.id}`)}
                          className={cn(
                            "cursor-pointer transition-colors hover:bg-orange-50 dark:hover:bg-slate-700/40",
                            isEven ? "bg-white dark:bg-transparent" : "bg-slate-50/60 dark:bg-slate-800/20"
                          )}>
                          <td className="px-4 py-3 font-mono text-xs font-semibold text-slate-900 dark:text-white">
                            {blade.serial_number}
                          </td>
                          <td className="px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-300">
                            {blade.melt_number}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className="font-mono text-sm font-bold text-slate-900 dark:text-white">
                              {(blade as BladeSortable).weight_grams
                                ? Number((blade as BladeSortable).weight_grams).toFixed(2)
                                : <span className="text-slate-400 dark:text-slate-500 font-normal text-xs">—</span>}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className="font-mono text-xs text-slate-600 dark:text-slate-300">
                              {(blade as BladeSortable).static_moment_gcm
                                ? Number((blade as BladeSortable).static_moment_gcm).toFixed(1)
                                : <span className="text-slate-400 dark:text-slate-500">—</span>}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold", cfg?.color ?? "bg-slate-400 text-white")}>
                              {cfg?.label ?? blade.status}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300 font-mono">
                            {blade.work_order_number ?? "—"}
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300 font-mono">
                            {(blade as any).engine_number ?? "—"}
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300 font-mono">
                            {blade.part_number ?? "—"}
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-400 dark:text-slate-500 whitespace-nowrap">
                            {formatDistanceToNow(parseISO(blade.created_at), { addSuffix: true })}
                          </td>
                          <td className="px-4 py-3">
                            <ChevronRight className="w-4 h-4 text-slate-300 dark:text-slate-600" />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Table footer — per-page + pagination */}
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-700/50 bg-slate-50 dark:bg-slate-800/30 flex-wrap gap-2">
              {/* Left: count + sort info */}
              <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                <span>
                  <span className="font-semibold text-slate-700 dark:text-slate-200">
                    {pageStart + 1}–{Math.min(pageStart + perPage, totalFiltered)}
                  </span>{" "}
                  of{" "}
                  <span className="font-semibold text-slate-700 dark:text-slate-200">
                    {totalFiltered}
                  </span>
                  {totalFiltered < allBladesTotal && (
                    <span className="text-orange-500"> (filtered from {allBladesTotal})</span>
                  )}
                </span>
                {sorted.length > 0 && (
                  <span>
                    Sorted by{" "}
                    <span className="font-medium text-orange-500">
                      {sortKey === "weight_grams" ? "Weight" :
                       sortKey === "static_moment" ? "Static Moment" :
                       sortKey === "serial_number" ? "Serial No." :
                       sortKey === "status" ? "Status" : "Date Added"}
                    </span>{" "}
                    {sortDir === "asc" ? "↑" : "↓"}
                  </span>
                )}
              </div>

              {/* Right: per-page selector + page nav */}
              <div className="flex items-center gap-3">
                {/* Per-page */}
                <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                  <span>Show</span>
                  {[10, 20, 50, 100].map((n) => (
                    <button
                      key={n}
                      onClick={() => { setPerPage(n); setCurrentPage(1); }}
                      className={cn(
                        "w-8 h-7 rounded-md text-xs font-medium transition-colors",
                        perPage === n
                          ? "bg-orange-500 text-white"
                          : "bg-white dark:bg-slate-700 border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:border-orange-400"
                      )}
                    >
                      {n}
                    </button>
                  ))}
                  <span>per page</span>
                </div>

                {/* Page navigation */}
                {totalPages > 1 && (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                      disabled={safeCurrentPage === 1}
                      className="w-8 h-7 rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 text-xs font-bold disabled:opacity-40 hover:border-orange-400 transition-colors"
                    >
                      ‹
                    </button>
                    {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                      const p = totalPages <= 7
                        ? i + 1
                        : safeCurrentPage <= 4
                          ? i + 1
                          : safeCurrentPage >= totalPages - 3
                            ? totalPages - 6 + i
                            : safeCurrentPage - 3 + i;
                      return (
                        <button key={p}
                          onClick={() => setCurrentPage(p)}
                          className={cn(
                            "w-8 h-7 rounded-md text-xs font-medium transition-colors",
                            safeCurrentPage === p
                              ? "bg-orange-500 text-white"
                              : "bg-white dark:bg-slate-700 border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:border-orange-400"
                          )}
                        >
                          {p}
                        </button>
                      );
                    })}
                    <button
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                      disabled={safeCurrentPage === totalPages}
                      className="w-8 h-7 rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 text-xs font-bold disabled:opacity-40 hover:border-orange-400 transition-colors"
                    >
                      ›
                    </button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
