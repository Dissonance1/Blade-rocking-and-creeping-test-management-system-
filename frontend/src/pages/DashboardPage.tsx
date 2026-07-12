import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Layers,
  XCircle,
  Plus,
  ArrowRight,
  RefreshCw,
  Activity,
  Wrench,
  Hash,
  ChevronDown,
  ArrowUp,
} from "lucide-react";
import { DashboardIcon } from "@/components/common/CustomIcons";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import KTIcon from "@/components/common/KTIcon";

import { workflowService } from "@/services/workflowService";
import { batchService, type BatchSummary } from "@/services/batchService";
import api from "@/services/api";
import type { BladeStatus, DashboardStats } from "@/types";
import { cn } from "@/utils/cn";

const REFRESH_TOAST_DURATION = 3000;

// ─── Refresh toast (bottom bar fills left-to-right over REFRESH_TOAST_DURATION) ─

function RefreshToast() {
  const [filled, setFilled] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setFilled(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className="w-full rounded-lg bg-green-50 dark:bg-green-950/50 shadow-lg overflow-hidden">
      <div className="flex items-start gap-2.5 px-4 py-3">
        <KTIcon iconName="check-circle" className="text-lg leading-none text-emerald-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-white">Dashboard refreshed</p>
        </div>
      </div>
      <div className="h-1 w-full bg-blue-100 dark:bg-blue-500/20">
        <div
          className="h-full bg-blue-500"
          style={{
            width: filled ? "100%" : "0%",
            transition: filled ? `width ${REFRESH_TOAST_DURATION}ms linear` : "none",
          }}
        />
      </div>
    </div>
  );
}

// ─── Status config ────────────────────────────────────────────────────────────

export const STATUS_CFG: Record<BladeStatus, { label: string; color: string }> = {
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

export type KpiAccent = "blue" | "amber" | "emerald" | "rose";

const KPI_ACCENT: Record<KpiAccent, { gradient: string; glow: string }> = {
  blue:    { gradient: "from-blue-400 to-blue-600",       glow: "shadow-blue-500/30" },
  amber:   { gradient: "from-amber-400 to-amber-600",     glow: "shadow-amber-500/30" },
  emerald: { gradient: "from-emerald-400 to-emerald-600", glow: "shadow-emerald-500/30" },
  rose:    { gradient: "from-rose-400 to-rose-600",       glow: "shadow-rose-500/30" },
};

export function KpiCard({ title, value, caption, icon, delta, accent }: {
  title: string; value: number | string; caption?: string;
  icon: React.ReactNode; delta?: number; accent: KpiAccent;
}) {
  const a = KPI_ACCENT[accent];
  return (
    <div className="h-24 w-full rounded-2xl border border-white/60 dark:border-white/10 bg-white/70 dark:bg-background backdrop-blur-xl p-3 shadow-xl shadow-slate-200/50 dark:shadow-black/20 flex flex-col justify-between">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center bg-gradient-to-br shadow-lg text-white shrink-0", a.gradient, a.glow)}>
            {icon}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-900 dark:text-white truncate">{title}</p>
            {caption && <p className="text-[10px] text-slate-400 dark:text-slate-300 truncate">{caption}</p>}
          </div>
        </div>
        {typeof delta === "number" && delta > 0 && (
          <span className="flex items-center gap-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 shrink-0">
            <ArrowUp className="w-3 h-3" /> +{delta}
          </span>
        )}
      </div>
      <p className="text-xl font-semibold tabular-nums tracking-tight mt-1 text-slate-900 dark:text-white">{value}</p>
    </div>
  );
}

// ─── Station card ───────────────────────────────────────────────────────────────

export function StationCard({ icon, iconBg, title, total, items, barColor, barPct }: {
  icon: React.ReactNode; iconBg: string; title: string; total: number;
  items: { label: string; value: number; dotColor: string }[];
  barColor: string; barPct: number;
}) {
  return (
    <div className="h-full rounded-2xl border border-white/60 dark:border-white/10 bg-white/70 dark:bg-background backdrop-blur-xl p-4 shadow-xl shadow-slate-200/50 dark:shadow-black/20 flex flex-col">
      <div className="flex items-center gap-3 mb-3">
        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-gradient-to-br shadow-lg text-white", iconBg)}>
          {icon}
        </div>
        <div>
          <p className="text-sm font-bold text-slate-900 dark:text-white">{title}</p>
          <p className="text-xs text-slate-400 dark:text-slate-300">{total} blade{total !== 1 ? "s" : ""} in process</p>
        </div>
      </div>
      <div className="space-y-1.5 flex-1">
        {items.map((it) => (
          <div key={it.label} className="flex items-center justify-between text-[11px]">
            <span className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
              <span className={cn("w-1.5 h-1.5 rounded-full", it.dotColor)} />
              {it.label}
            </span>
            <span className="font-semibold text-slate-900 dark:text-white">{it.value}</span>
          </div>
        ))}
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/15 overflow-hidden mt-3">
        <div className={cn("h-full rounded-full", barColor)} style={{ width: `${barPct}%` }} />
      </div>
    </div>
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
  const { data: stats, refetch, isFetching } = useQuery<DashboardStats>({
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

  async function handleRefresh() {
    await refetch();
    toast.custom(() => <RefreshToast />, { duration: REFRESH_TOAST_DURATION, unstyled: true });
  }

  // Status distribution — full workflow order
  const STATUS_ORDER: BladeStatus[] = [
    "CREATED", "OH_INSPECTION", "MEASUREMENTS_RECORDED", "SENT_TO_ASSEMBLY",
    "ASSEMBLY_RECEIVED", "ASSEMBLY_VERIFIED", "SLOT_ASSIGNED",
    "BALANCING_IN_PROGRESS", "BALANCING_COMPLETED", "RETURNED_TO_OH",
    "FINAL_VERIFICATION", "COMPLETED", "ON_HOLD", "REJECTED", "REOPENED",
  ];
  const maxStatusCount = Math.max(1, ...STATUS_ORDER.map((s) => byStatus[s] ?? 0));

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <DashboardIcon className="w-5 h-5 text-orange-500 shrink-0" />
              Operations Dashboard
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 tracking-tight">
              Real-time blade tracking across all stations.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={handleRefresh} disabled={isFetching}
              className="h-8 px-3 text-xs flex-1 sm:flex-none justify-center border-2 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 gap-1.5 w-full sm:w-36">
              <RefreshCw className={cn("w-3 h-3", isFetching && "animate-spin")} />
              Refresh
            </Button>
            <Button onClick={() => navigate("/blades/new")}
              className="h-8 px-3 text-xs flex-1 sm:flex-none justify-center bg-gradient-to-br from-orange-400 to-orange-600 hover:from-orange-500 hover:to-orange-700 text-white shadow-lg shadow-orange-500/30 border-0 gap-1.5 w-full sm:w-36">
              <Plus className="w-3 h-3" /> New Blade Entry
            </Button>
            <Button variant="outline" onClick={() => navigate("/assembly-queue")}
              className="h-8 px-3 text-xs flex-1 sm:flex-none justify-center bg-white hover:bg-slate-50 border-2 border-slate-300 dark:bg-background dark:hover:bg-slate-900 dark:border-slate-700 text-slate-900 dark:text-white gap-1.5 w-full sm:w-36">
              Assembly Queue <ArrowRight className="w-3 h-3" />
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 w-full px-4 sm:px-6 py-3 flex flex-col gap-4 overflow-y-auto">

        {/* ── KPI cards ────────────────────────────────────────────────────── */}
        <div className="shrink-0 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4 items-start">
          <KpiCard title="Total Blades" value={totalBlades}
            caption={`${activeBatches.length} active batch${activeBatches.length !== 1 ? "es" : ""}`}
            icon={<KTIcon iconName="category" className="text-xl leading-none" />} delta={todayCreated} accent="blue" />
          <KpiCard title="In Progress" value={inProgressCount}
            caption="Across all stations"
            icon={<KTIcon iconName="time" className="text-xl leading-none" />} accent="amber" />
          <KpiCard title="Completed" value={completedCount}
            caption={`${completionRate.toFixed(1)}% completion rate`}
            icon={<KTIcon iconName="check-circle" className="text-xl leading-none" />} delta={todayCompleted} accent="emerald" />
          <KpiCard title="On Hold" value={onHoldCount}
            caption="Needs attention"
            icon={<KTIcon iconName="flag" className="text-xl leading-none" />} accent="rose" />
        </div>

        {/* ── Station cards ────────────────────────────────────────────────── */}
        <div className="shrink-0 grid grid-cols-1 lg:grid-cols-3 gap-4">
          <StationCard
            icon={<KTIcon iconName="gear" className="text-xl leading-none" />}
            iconBg="from-sky-400 to-sky-600 shadow-sky-500/30"
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
            icon={<KTIcon iconName="flash-circle" className="text-xl leading-none" />}
            iconBg="from-orange-400 to-orange-600 shadow-orange-500/30"
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
            icon={<KTIcon iconName="shield-tick" className="text-xl leading-none" />}
            iconBg="from-emerald-400 to-emerald-600 shadow-emerald-500/30"
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

        {/* ── Work Order / Engine Summary ─────────────────────────────────── */}
        {workOrders.length > 0 && (
          <div className="shrink-0 bg-white/70 dark:bg-background backdrop-blur-xl rounded-2xl border border-white/60 dark:border-white/10 shadow-xl shadow-slate-200/50 dark:shadow-black/20 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-slate-800 dark:bg-background">
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
                  <div className="absolute right-0 top-full mt-1 z-20 bg-white dark:bg-background rounded-xl border border-slate-200 dark:border-slate-700 shadow-xl min-w-[220px] max-h-60 overflow-y-auto">
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
                  <div key={label} className="px-3 py-2">
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="text-slate-400 dark:text-slate-300">{icon}</span>
                      <span className="text-slate-400 dark:text-slate-300 text-[10px] font-semibold uppercase tracking-widest">{label}</span>
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
          <div className="shrink-0 rounded-xl bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 p-4">
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

        {/* ── Active Batches + Status Distribution ────────────────────────── */}
        <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card className="bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 flex flex-col min-h-0">
            <CardHeader className="shrink-0 pb-3 border-b border-slate-100 dark:border-slate-700/50 pt-4">
              <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-3">
                <span className="w-9 h-9 rounded-xl flex items-center justify-center bg-gradient-to-br from-teal-400 to-cyan-600 shadow-md shadow-cyan-500/30 text-white shrink-0">
                  <KTIcon iconName="chart-line-up" className="text-xl leading-none" />
                </span>
                Active Batches
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 min-h-0 overflow-y-auto pt-3">
              {activeBatches.length === 0 ? (
                <div className="text-center py-10 text-slate-400 dark:text-slate-300 text-base">
                  No active batches
                </div>
              ) : (
                <div className="space-y-4">
                  {activeBatches.slice(0, 5).map((b) => {
                    const pct = b.blade_count > 0 ? (b.blades_completed / b.blade_count) * 100 : 0;
                    return (
                      <div key={b.batch_number}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="min-w-0">
                            <p className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                              {b.batch_number}
                            </p>
                            <p className="text-xs text-slate-400 dark:text-slate-300 truncate">
                              {b.work_order_number ?? "—"} · {b.part_number ?? b.nomenclature ?? "—"}
                            </p>
                          </div>
                          <span className="text-sm font-bold text-orange-500 shrink-0 ml-2">
                            {pct.toFixed(0)}%
                          </span>
                        </div>
                        <div className="h-2.5 rounded-full bg-slate-100 dark:bg-white/15 overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-500"
                            style={{ width: `${pct}%` }} />
                        </div>
                        <p className="text-xs text-slate-400 dark:text-slate-300 mt-1">
                          {b.blades_completed} / {b.blade_count} blades completed
                        </p>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 flex flex-col min-h-0">
            <CardHeader className="shrink-0 pb-3 border-b border-slate-100 dark:border-slate-700/50 pt-4">
              <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-3">
                <span className="w-9 h-9 rounded-xl flex items-center justify-center bg-gradient-to-br from-violet-400 to-violet-600 shadow-md shadow-violet-500/30 text-white shrink-0">
                  <KTIcon iconName="chart-pie-simple" className="text-xl leading-none" />
                </span>
                Status Distribution
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 min-h-0 flex flex-col gap-1 pt-2 overflow-y-auto pb-2">
              {STATUS_ORDER.map((s) => {
                const cfg = STATUS_CFG[s];
                const count = byStatus[s] ?? 0;
                const pct = (count / maxStatusCount) * 100;
                const dotColor = cfg.color.split(" ")[0];
                return (
                  <div key={s} className="flex items-center gap-2">
                    <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", dotColor)} />
                    <span className="w-32 shrink-0 text-[11px] text-slate-600 dark:text-slate-300 truncate">
                      {cfg.label}
                    </span>
                    <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-white/15 overflow-hidden">
                      <div className={cn("h-full rounded-full", dotColor)} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-6 shrink-0 text-right text-[11px] font-semibold text-slate-700 dark:text-slate-200">
                      {count}
                    </span>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </div>

      </div>

    </div>
  );
}
