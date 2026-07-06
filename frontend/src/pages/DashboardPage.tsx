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
  ArrowUp,
  PauseCircle,
  Cog,
  Zap,
  ShieldCheck,
  BarChart3,
  TrendingUp,
  Kanban,
  Cpu,
  FileBarChart,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { workflowService } from "@/services/workflowService";
import { batchService, type BatchSummary } from "@/services/batchService";
import api from "@/services/api";
import type { BladeStatus, DashboardStats } from "@/types";
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

// ─── KPI card (operations-dashboard style) ─────────────────────────────────────

type KpiAccent = "blue" | "amber" | "emerald" | "rose";

const KPI_ACCENT: Record<KpiAccent, { bg: string; text: string }> = {
  blue:    { bg: "bg-blue-100 dark:bg-blue-500/15",       text: "text-blue-600 dark:text-blue-400" },
  amber:   { bg: "bg-amber-100 dark:bg-amber-500/15",     text: "text-amber-600 dark:text-amber-400" },
  emerald: { bg: "bg-emerald-100 dark:bg-emerald-500/15", text: "text-emerald-600 dark:text-emerald-400" },
  rose:    { bg: "bg-rose-100 dark:bg-rose-500/15",       text: "text-rose-600 dark:text-rose-400" },
};

function KpiCard({ title, value, caption, icon, delta, accent }: {
  title: string; value: number | string; caption?: string;
  icon: React.ReactNode; delta?: number; accent: KpiAccent;
}) {
  const a = KPI_ACCENT[accent];
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/60 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center", a.bg, a.text)}>
          {icon}
        </div>
        {typeof delta === "number" && delta > 0 && (
          <span className="flex items-center gap-0.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
            <ArrowUp className="w-3 h-3" /> +{delta}
          </span>
        )}
      </div>
      <p className="text-3xl font-bold mt-3 text-slate-900 dark:text-white">{value}</p>
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300 mt-0.5">{title}</p>
      {caption && <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{caption}</p>}
    </div>
  );
}

// ─── Station card ───────────────────────────────────────────────────────────────

function StationCard({ icon, iconBg, title, total, items, barColor, barPct }: {
  icon: React.ReactNode; iconBg: string; title: string; total: number;
  items: { label: string; value: number; dotColor: string }[];
  barColor: string; barPct: number;
}) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/60 p-5 shadow-sm flex flex-col">
      <div className="flex items-center gap-3 mb-4">
        <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center shrink-0", iconBg)}>
          {icon}
        </div>
        <div>
          <p className="text-sm font-bold text-slate-900 dark:text-white">{title}</p>
          <p className="text-xs text-slate-400 dark:text-slate-500">{total} blade{total !== 1 ? "s" : ""} in process</p>
        </div>
      </div>
      <div className="space-y-2 flex-1">
        {items.map((it) => (
          <div key={it.label} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
              <span className={cn("w-1.5 h-1.5 rounded-full", it.dotColor)} />
              {it.label}
            </span>
            <span className="font-semibold text-slate-900 dark:text-white">{it.value}</span>
          </div>
        ))}
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-700/50 overflow-hidden mt-4">
        <div className={cn("h-full rounded-full", barColor)} style={{ width: `${barPct}%` }} />
      </div>
    </div>
  );
}

// ─── Quick action ───────────────────────────────────────────────────────────────

function QuickAction({ icon, iconBg, label, onClick }: {
  icon: React.ReactNode; iconBg: string; label: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-3 rounded-xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/60 px-4 py-4 text-left hover:border-orange-300 dark:hover:border-orange-500/50 hover:shadow-md transition-all"
    >
      <span className={cn("w-9 h-9 rounded-lg flex items-center justify-center shrink-0", iconBg)}>
        {icon}
      </span>
      <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{label}</span>
    </button>
  );
}

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

  const { data: batches = [] } = useQuery<BatchSummary[]>({
    queryKey: ["dashboard-batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  const { data: throughputToday = [] } = useQuery<
    { date: string; created: number; completed: number; rejected: number }[]
  >({
    queryKey: ["dashboard-throughput-today"],
    queryFn: () => workflowService.getDailyThroughput(1),
    refetchInterval: 60_000,
  });

  const activeWO: WorkOrderSummary | null =
    workOrders.find((w) => w.work_order_number === selectedWO) ??
    workOrders[0] ?? null;

  // ── Operations-dashboard derived values ──────────────────────────────────
  const byStatus = (stats?.by_status ?? {}) as Partial<Record<BladeStatus, number>>;
  const totalBlades = Object.values(byStatus).reduce((a, b) => a + (b ?? 0), 0);
  const onHoldCount = byStatus.ON_HOLD ?? 0;
  const inProgressCount = Math.max(0, (stats?.total_active ?? 0) - onHoldCount);
  const completedCount = stats?.total_completed ?? 0;
  const completionRate = totalBlades > 0 ? (completedCount / totalBlades) * 100 : 0;
  const todayCreated = throughputToday[0]?.created ?? 0;
  const todayCompleted = throughputToday[0]?.completed ?? 0;
  const activeBatches = batches.filter((b) => b.blades_completed < b.blade_count);

  // Overhaul Hangar
  const ohInspection = byStatus.OH_INSPECTION ?? 0;
  const ohMeasurement = byStatus.MEASUREMENTS_RECORDED ?? 0;
  const ohTotal = ohInspection + ohMeasurement;

  // Assembly Hangar
  const asmQueued = (byStatus.SENT_TO_ASSEMBLY ?? 0) + (byStatus.ASSEMBLY_RECEIVED ?? 0) + (byStatus.ASSEMBLY_VERIFIED ?? 0);
  const asmSlotted = byStatus.SLOT_ASSIGNED ?? 0;
  const asmBalancing = (byStatus.BALANCING_IN_PROGRESS ?? 0) + (byStatus.BALANCING_COMPLETED ?? 0);
  const asmTotal = asmQueued + asmSlotted + asmBalancing;

  // Final Verification
  const fvReturned = byStatus.RETURNED_TO_OH ?? 0;
  const fvVerifying = byStatus.FINAL_VERIFICATION ?? 0;
  const fvTotal = fvReturned + fvVerifying;

  const maxStationTotal = Math.max(ohTotal, asmTotal, fvTotal, 1);

  // Status distribution — full workflow order
  const STATUS_ORDER: BladeStatus[] = [
    "CREATED", "OH_INSPECTION", "MEASUREMENTS_RECORDED", "SENT_TO_ASSEMBLY",
    "ASSEMBLY_RECEIVED", "ASSEMBLY_VERIFIED", "SLOT_ASSIGNED",
    "BALANCING_IN_PROGRESS", "BALANCING_COMPLETED", "RETURNED_TO_OH",
    "FINAL_VERIFICATION", "COMPLETED", "ON_HOLD", "REJECTED", "REOPENED",
  ];
  const maxStatusCount = Math.max(1, ...STATUS_ORDER.map((s) => byStatus[s] ?? 0));

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
              Real-time blade tracking across all stations
              {dataUpdatedAt && (
                <span className="text-slate-400 dark:text-slate-500">
                  {" · "}Last updated {formatDistanceToNow(dataUpdatedAt, { addSuffix: true })}
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-3">
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

        {/* ── KPI cards ────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          <KpiCard title="Total Blades" value={totalBlades}
            caption={`${activeBatches.length} active batch${activeBatches.length !== 1 ? "es" : ""}`}
            icon={<Layers className="w-5 h-5" />} delta={todayCreated} accent="blue" />
          <KpiCard title="In Progress" value={inProgressCount}
            caption="Across all stations"
            icon={<Clock className="w-5 h-5" />} accent="amber" />
          <KpiCard title="Completed" value={completedCount}
            caption={`${completionRate.toFixed(1)}% completion rate`}
            icon={<CheckCircle2 className="w-5 h-5" />} delta={todayCompleted} accent="emerald" />
          <KpiCard title="On Hold" value={onHoldCount}
            caption="Needs attention"
            icon={<PauseCircle className="w-5 h-5" />} accent="rose" />
        </div>

        {/* ── Station cards ────────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <StationCard
            icon={<Cog className="w-5 h-5" />}
            iconBg="bg-sky-100 dark:bg-sky-500/15 text-sky-600 dark:text-sky-400"
            title="Overhaul Hangar"
            total={ohTotal}
            items={[
              { label: "Inspection", value: ohInspection, dotColor: "bg-sky-500" },
              { label: "Measurement", value: ohMeasurement, dotColor: "bg-sky-500" },
            ]}
            barColor="bg-sky-500"
            barPct={(ohTotal / maxStationTotal) * 100}
          />
          <StationCard
            icon={<Zap className="w-5 h-5" />}
            iconBg="bg-orange-100 dark:bg-orange-500/15 text-orange-600 dark:text-orange-400"
            title="Assembly Hangar"
            total={asmTotal}
            items={[
              { label: "Queued", value: asmQueued, dotColor: "bg-orange-500" },
              { label: "Slotted", value: asmSlotted, dotColor: "bg-orange-500" },
              { label: "Balancing", value: asmBalancing, dotColor: "bg-orange-500" },
            ]}
            barColor="bg-orange-500"
            barPct={(asmTotal / maxStationTotal) * 100}
          />
          <StationCard
            icon={<ShieldCheck className="w-5 h-5" />}
            iconBg="bg-emerald-100 dark:bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            title="Final Verification"
            total={fvTotal}
            items={[
              { label: "Returned", value: fvReturned, dotColor: "bg-emerald-500" },
              { label: "Verifying", value: fvVerifying, dotColor: "bg-emerald-500" },
            ]}
            barColor="bg-emerald-500"
            barPct={(fvTotal / maxStationTotal) * 100}
          />
        </div>

        {/* ── Active Batches + Status Distribution ────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
            <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
              <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-orange-500" />
                Active Batches
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              {activeBatches.length === 0 ? (
                <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-sm">
                  No active batches
                </div>
              ) : (
                <div className="space-y-5">
                  {activeBatches.slice(0, 5).map((b) => {
                    const pct = b.blade_count > 0 ? (b.blades_completed / b.blade_count) * 100 : 0;
                    return (
                      <div key={b.batch_number}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="min-w-0">
                            <p className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                              {b.batch_number}
                            </p>
                            <p className="text-xs text-slate-400 dark:text-slate-500 truncate">
                              {b.work_order_number ?? "—"} · {b.part_number ?? b.nomenclature ?? "—"}
                            </p>
                          </div>
                          <span className="text-sm font-bold text-orange-500 shrink-0 ml-2">
                            {pct.toFixed(0)}%
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-700/50 overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-500"
                            style={{ width: `${pct}%` }} />
                        </div>
                        <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
                          {b.blades_completed} / {b.blade_count} blades completed
                        </p>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
            <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
              <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-orange-500" />
                Status Distribution
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="space-y-2.5">
                {STATUS_ORDER.map((s) => {
                  const cfg = STATUS_CFG[s];
                  const count = byStatus[s] ?? 0;
                  const pct = (count / maxStatusCount) * 100;
                  const dotColor = cfg.color.split(" ")[0];
                  return (
                    <div key={s} className="flex items-center gap-3">
                      <span className={cn("w-2 h-2 rounded-full shrink-0", dotColor)} />
                      <span className="w-32 shrink-0 text-xs text-slate-600 dark:text-slate-300 truncate">
                        {cfg.label}
                      </span>
                      <div className="flex-1 h-2 rounded-full bg-slate-100 dark:bg-slate-700/50 overflow-hidden">
                        <div className={cn("h-full rounded-full", dotColor)} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="w-6 shrink-0 text-right text-xs font-semibold text-slate-700 dark:text-slate-200">
                        {count}
                      </span>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ── Quick actions ────────────────────────────────────────────────── */}
        <div>
          <h2 className="text-xs font-bold tracking-widest uppercase text-slate-400 dark:text-slate-500 mb-3">
            Quick Actions
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <QuickAction
              icon={<Kanban className="w-4 h-4" />}
              iconBg="bg-orange-100 dark:bg-orange-500/15 text-orange-600 dark:text-orange-400"
              label="Workflow Board"
              onClick={() => navigate("/batch-tracking")}
            />
            <QuickAction
              icon={<Cpu className="w-4 h-4" />}
              iconBg="bg-sky-100 dark:bg-sky-500/15 text-sky-600 dark:text-sky-400"
              label="Instrument Data"
              onClick={() => navigate("/rocking-creep")}
            />
            <QuickAction
              icon={<FileBarChart className="w-4 h-4" />}
              iconBg="bg-emerald-100 dark:bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
              label="QA Reports"
              onClick={() => navigate("/reports")}
            />
          </div>
        </div>

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

      </div>
    </div>
  );
}
