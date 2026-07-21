import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Layers,
  Clock,
  CheckCircle2,
  XCircle,
  Activity,
  Cog,
  Zap,
  ShieldCheck,
  BarChart3,
  TrendingUp,
  FileText,
  FileSpreadsheet,
  Download,
  Loader2,
  ArrowRight,
} from "lucide-react";
import { formatDistanceToNow, format, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { workflowService } from "@/services/workflowService";
import { batchService, type BatchSummary } from "@/services/batchService";
import { reportService } from "@/services/reportService";
import type { BladeStatus, DashboardStats, Report } from "@/types";
import { cn } from "@/utils/cn";
import { KpiCard, StationCard, STATUS_CFG } from "./DashboardPage";

// ─── Report status badge (compact) ─────────────────────────────────────────────

function ReportStatusBadge({ status }: { status: Report["status"] }) {
  switch (status) {
    case "COMPLETED":
    case "READY":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500 px-2 py-0.5 text-xs font-semibold text-white">
          <CheckCircle2 className="w-3 h-3" /> Ready
        </span>
      );
    case "GENERATING":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-500 px-2 py-0.5 text-xs font-semibold text-white">
          <Loader2 className="w-3 h-3 animate-spin" /> Generating
        </span>
      );
    case "FAILED":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-500 px-2 py-0.5 text-xs font-semibold text-white">
          <XCircle className="w-3 h-3" /> Failed
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-slate-500 px-2 py-0.5 text-xs font-semibold text-white">
          <Clock className="w-3 h-3" /> Pending
        </span>
      );
  }
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function QaDashboardPage() {
  const navigate = useNavigate();

  const { data: stats, dataUpdatedAt, refetch, isFetching } = useQuery<DashboardStats>({
    queryKey: ["qa-dashboard-stats"],
    queryFn: workflowService.getDashboardStats,
    refetchInterval: 30_000,
  });

  const { data: batches = [] } = useQuery<BatchSummary[]>({
    queryKey: ["qa-dashboard-batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  const { data: reportsData } = useQuery({
    queryKey: ["qa-dashboard-reports"],
    queryFn: () => reportService.list({ limit: 5 }),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const hasGenerating = items.some((r) => r.status === "GENERATING" || r.status === "PENDING");
      return hasGenerating ? 3000 : 15_000;
    },
  });
  const recentReports: Report[] = reportsData?.items ?? [];

  const byStatus = (stats?.by_status ?? {}) as Partial<Record<BladeStatus, number>>;
  const totalBlades = Object.values(byStatus).reduce((a, b) => a + (b ?? 0), 0);
  const inProgressCount = stats?.total_active ?? 0;
  const completedCount = stats?.total_completed ?? 0;
  const completionRate = totalBlades > 0 ? (completedCount / totalBlades) * 100 : 0;
  const activeBatches = batches.filter((b) => b.blades_completed < b.blade_count);

  const ohInspection = byStatus.OH_INSPECTION ?? 0;
  const ohMeasurement = byStatus.MEASUREMENTS_RECORDED ?? 0;
  const ohTotal = ohInspection + ohMeasurement;

  const asmQueued = (byStatus.SENT_TO_ASSEMBLY ?? 0) + (byStatus.ASSEMBLY_RECEIVED ?? 0) + (byStatus.ASSEMBLY_VERIFIED ?? 0);
  const asmSlotted = byStatus.SLOT_ASSIGNED ?? 0;
  const asmBalancing = (byStatus.BALANCING_IN_PROGRESS ?? 0) + (byStatus.BALANCING_COMPLETED ?? 0);
  const asmTotal = asmQueued + asmSlotted + asmBalancing;

  const fvReturned = byStatus.RETURNED_TO_OH ?? 0;
  const fvVerifying = byStatus.FINAL_VERIFICATION ?? 0;
  const fvTotal = fvReturned + fvVerifying;

  const maxStationTotal = Math.max(ohTotal, asmTotal, fvTotal, 1);

  const STATUS_ORDER: BladeStatus[] = [
    "CREATED", "OH_INSPECTION", "MEASUREMENTS_RECORDED", "SENT_TO_ASSEMBLY",
    "ASSEMBLY_RECEIVED", "ASSEMBLY_VERIFIED", "SLOT_ASSIGNED",
    "BALANCING_IN_PROGRESS", "BALANCING_COMPLETED", "RETURNED_TO_OH",
    "FINAL_VERIFICATION", "COMPLETED", "REJECTED", "REOPENED",
  ];
  const maxStatusCount = Math.max(1, ...STATUS_ORDER.map((s) => byStatus[s] ?? 0));

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-slate-100 dark:bg-background text-slate-900 dark:text-white">
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-background px-6 py-4 shadow-sm">
        <div className="flex items-center justify-between max-w-screen-2xl mx-auto">
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2 text-slate-900 dark:text-white">
              <Activity className="w-5 h-5 text-orange-500" />
              QA Dashboard
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Read-only overview of blade tracking across all stations
              {dataUpdatedAt && (
                <span className="text-slate-400 dark:text-slate-500">
                  {" · "}Last updated {formatDistanceToNow(dataUpdatedAt, { addSuffix: true })}
                </span>
              )}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}
            className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 gap-1.5">
            <BarChart3 className={cn("w-3.5 h-3.5", isFetching && "animate-pulse")} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto max-w-screen-2xl w-full mx-auto px-6 py-6 pb-10 space-y-5">

        {/* ── KPI cards ────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
          <KpiCard title="Total Blades" value={totalBlades}
            caption={`${activeBatches.length} active batch${activeBatches.length !== 1 ? "es" : ""}`}
            icon={<Layers className="w-5 h-5" />} accent="blue" />
          <KpiCard title="In Progress" value={inProgressCount}
            caption="Across all stations"
            icon={<Clock className="w-5 h-5" />} accent="amber" />
          <KpiCard title="Completed" value={completedCount}
            caption={`${completionRate.toFixed(1)}% completion rate`}
            icon={<CheckCircle2 className="w-5 h-5" />} accent="emerald" />
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
          <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
            <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50 flex-row items-center justify-between">
              <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-orange-500" />
                Active Batches
              </CardTitle>
              <Button variant="ghost" size="sm" onClick={() => navigate("/batch-tracking")}
                className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white gap-1">
                View all <ArrowRight className="w-3.5 h-3.5" />
              </Button>
            </CardHeader>
            <CardContent className="pt-4">
              {activeBatches.length === 0 ? (
                <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-sm">
                  No active batches
                </div>
              ) : (
                <div className="space-y-5">
                  {activeBatches.slice(0, 5).map((b) => {
                    const pct = (b.rows_complete_count / 90) * 100;
                    return (
                      <div key={b.work_order_number}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="min-w-0">
                            <p className="text-sm font-semibold text-slate-900 dark:text-white truncate flex items-center gap-1.5">
                              {b.work_order_number}
                              <span className={cn(
                                "inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold shrink-0",
                                b.blade_type === "HPTR"
                                  ? "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                                  : "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                              )}>
                                {b.blade_type ?? "LPTR"}
                              </span>
                            </p>
                            <p className="text-xs text-slate-400 dark:text-slate-500 truncate">
                              {b.part_number ?? "—"}
                            </p>
                          </div>
                          <span className="text-sm font-bold text-orange-500 shrink-0 ml-2">
                            {pct.toFixed(0)}%
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-100 dark:bg-background overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-500"
                            style={{ width: `${pct}%` }} />
                        </div>
                        <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
                          {b.rows_complete_count} / 90 blades entered
                        </p>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
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
                      <div className="flex-1 h-2 rounded-full bg-slate-100 dark:bg-background overflow-hidden">
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

        {/* ── Reports ───────────────────────────────────────────────────────── */}
        <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
          <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50 flex-row items-center justify-between">
            <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
              <FileText className="w-4 h-4 text-orange-500" />
              Reports
            </CardTitle>
            <Button size="sm" onClick={() => navigate("/reports")}
              className="bg-orange-500 hover:bg-orange-600 text-white gap-1.5">
              Generate New Report <ArrowRight className="w-3.5 h-3.5" />
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {recentReports.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-400 dark:text-slate-500">
                <FileText className="w-10 h-10 mb-3 opacity-20" />
                <p className="font-medium text-sm">No reports yet</p>
                <p className="text-xs mt-1">Generate one to download blade/batch data as PDF or Excel</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-100 dark:divide-slate-700/50">
                {recentReports.map((report) => (
                  <div key={report.id} className="flex items-center justify-between px-5 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      {report.report_type === "PDF" ? (
                        <FileText className="w-4 h-4 text-red-500 shrink-0" />
                      ) : (
                        <FileSpreadsheet className="w-4 h-4 text-emerald-500 shrink-0" />
                      )}
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
                          {report.name || `Report #${report.id}`}
                        </p>
                        <p className="text-xs text-slate-400 dark:text-slate-500">
                          {format(parseISO(report.created_at), "dd MMM yyyy HH:mm")}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <ReportStatusBadge status={report.status} />
                      {(report.status === "COMPLETED" || report.status === "READY") && (report.file_url ?? report.file_path) && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => reportService.download(report.id, report.name)}
                          className="border-2 border-emerald-400 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-600/20 h-8 text-xs gap-1"
                        >
                          <Download className="w-3 h-3" />
                          Download
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

      </div>
    </div>
  );
}
