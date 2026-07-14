import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  Ruler,
  Package,
  ScanLine,
  Loader2,
  ArrowRight,
  RotateCcw,
  History,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { format, parseISO, formatDistanceToNow } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { bladeService } from "@/services/bladeService";
import { workflowService } from "@/services/workflowService";
import { useAuthStore } from "@/store/authStore";
import type { BladeStatus, WorkflowLog } from "@/types";
import { cn } from "@/utils/cn";

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CFG: Record<
  BladeStatus,
  { label: string; variant: string; dot: string }
> = {
  CREATED: { label: "Created", variant: "bg-indigo-500 text-white", dot: "bg-indigo-500" },
  OH_INSPECTION: { label: "OH Inspection", variant: "bg-amber-500 text-white", dot: "bg-amber-500" },
  MEASUREMENTS_RECORDED: { label: "Measurements Recorded", variant: "bg-blue-500 text-white", dot: "bg-blue-500" },
  SENT_TO_ASSEMBLY: { label: "Sent to Assembly", variant: "bg-violet-500 text-white", dot: "bg-violet-500" },
  ASSEMBLY_RECEIVED: { label: "Received at Assembly", variant: "bg-sky-500 text-white", dot: "bg-sky-500" },
  ASSEMBLY_VERIFIED: { label: "Assembly Verified", variant: "bg-emerald-600 text-white", dot: "bg-emerald-600" },
  SLOT_ASSIGNED: { label: "Slot Assigned", variant: "bg-cyan-500 text-white", dot: "bg-cyan-500" },
  BALANCING_IN_PROGRESS: { label: "Balancing In Progress", variant: "bg-orange-500 text-white", dot: "bg-orange-500" },
  BALANCING_COMPLETED: { label: "Balancing Completed", variant: "bg-emerald-500 text-white", dot: "bg-emerald-500" },
  RETURNED_TO_OH: { label: "Returned to OH", variant: "bg-amber-500 text-white", dot: "bg-amber-500" },
  FINAL_VERIFICATION: { label: "Final Verification", variant: "bg-lime-500 text-white", dot: "bg-lime-500" },
  COMPLETED: { label: "Completed", variant: "bg-green-500 text-white", dot: "bg-green-500" },
  REJECTED: { label: "Rejected", variant: "bg-red-500 text-white", dot: "bg-red-500" },
  ON_HOLD: { label: "On Hold", variant: "bg-slate-500 text-white", dot: "bg-slate-500" },
  REOPENED: { label: "Reopened", variant: "bg-amber-500 text-white", dot: "bg-amber-500" },
};

function StatusBadge({ status }: { status: BladeStatus }) {
  const cfg = STATUS_CFG[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold",
        cfg.variant
      )}
    >
      <span className="w-2 h-2 rounded-full bg-white/60" />
      {cfg.label}
    </span>
  );
}

function InfoField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-slate-500 dark:text-slate-400 text-xs font-medium uppercase tracking-wide mb-0.5">
        {label}
      </dt>
      <dd className="text-slate-900 dark:text-white text-sm font-medium">{value ?? "—"}</dd>
    </div>
  );
}

function WorkflowTimeline({ logs }: { logs: WorkflowLog[] }) {
  return (
    <ol className="space-y-0">
      {logs.map((log, idx) => {
        const cfg = STATUS_CFG[log.to_status];
        const isLatest = idx === 0;
        const isLast = idx === logs.length - 1;
        return (
          <li key={log.id} className="relative flex gap-3 pb-5 last:pb-0">
            <div className="flex flex-col items-center shrink-0">
              <div
                className={cn(
                  "w-4 h-4 rounded-full border-2 border-white dark:border-slate-900 shadow shrink-0 z-10",
                  isLatest ? cfg.dot : "bg-slate-400 dark:bg-background"
                )}
              />
              {!isLast && (
                <div className="w-0.5 flex-1 bg-slate-300 dark:bg-background mt-1" />
              )}
            </div>

            <div
              className={cn(
                "flex-1 rounded-xl border p-3 mb-1",
                isLatest
                  ? "border-orange-200 dark:border-slate-600 bg-orange-50 dark:bg-background"
                  : "border-slate-200 dark:border-slate-700/40 bg-white dark:bg-background"
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="space-y-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {log.from_status && (
                      <>
                        <span className="text-slate-400 dark:text-slate-500 text-xs truncate">
                          {STATUS_CFG[log.from_status]?.label ?? log.from_status}
                        </span>
                        <ArrowRight className="w-3 h-3 text-slate-400 dark:text-slate-500 shrink-0" />
                      </>
                    )}
                    <span
                      className={cn(
                        "text-xs font-bold",
                        isLatest
                          ? "text-orange-600 dark:text-orange-400"
                          : "text-slate-700 dark:text-slate-300"
                      )}
                    >
                      {cfg?.label ?? log.to_status}
                    </span>
                    {isLatest && (
                      <span className="rounded-full bg-orange-500 text-white px-1.5 py-0.5 text-[10px] font-semibold leading-none">
                        Current
                      </span>
                    )}
                  </div>
                  {log.remarks && (
                    <p className="text-slate-500 dark:text-slate-400 text-xs italic">
                      "{log.remarks}"
                    </p>
                  )}
                  <p className="text-slate-400 dark:text-slate-500 text-xs">
                    by{" "}
                    <span className="font-medium text-slate-500 dark:text-slate-400">
                      {log.action_by_id}
                    </span>
                  </p>
                </div>
                <time className="text-slate-400 dark:text-slate-500 text-xs whitespace-nowrap shrink-0 mt-0.5">
                  {formatDistanceToNow(parseISO(log.timestamp), { addSuffix: true })}
                </time>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function BladeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const hasRole = useAuthStore((s) => s.hasRole);

  const { data: blade, isLoading } = useQuery({
    queryKey: ["blade", id],
    queryFn: () => bladeService.get(id!),
    enabled: !!id,
  });

  const { data: history } = useQuery({
    queryKey: ["blade-history", id],
    queryFn: () => workflowService.getTransitions(id!),
    enabled: !!id,
  });

  const transitionMutation = useMutation({
    mutationFn: ({
      to_status,
      remarks,
    }: {
      to_status: BladeStatus;
      remarks?: string | undefined;
    }) =>
      bladeService.transition(id!, {
        to_status,
        ...(remarks !== undefined ? { remarks } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["blade", id] });
      queryClient.invalidateQueries({ queryKey: ["blade-history", id] });
      queryClient.invalidateQueries({ queryKey: ["blades"] });
    },
  });

  if (isLoading) {
    return (
      <div className="h-full bg-slate-100 dark:bg-background flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-orange-500" />
      </div>
    );
  }

  if (!blade) {
    return (
      <div className="h-full bg-slate-100 dark:bg-background flex items-center justify-center text-slate-500 dark:text-slate-400 text-center px-4">
        Blade not found.
      </div>
    );
  }

  const logs: WorkflowLog[] = history?.logs ?? [];

  const measurementChartData = [
    { name: "Rocking", value: blade.measurements?.[0]?.rocking_value ?? 0, fill: "#f29a25" },
    { name: "Creep", value: blade.measurements?.[0]?.creep_value ?? 0, fill: "#8b5cf6" },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-4 shadow-none border-b-0">
        <div className="w-full flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
          <div className="flex items-center gap-3 sm:gap-4 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => navigate(-1)}
              className="shrink-0 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
            >
              <ArrowLeft className="w-4 h-4" />
            </Button>
            <div className="min-w-0">
              <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
                <h1 className="text-xl sm:text-2xl font-bold font-mono text-slate-900 dark:text-white truncate">
                  {blade.serial_number}
                </h1>
                <StatusBadge status={blade.status} />
                {blade.ocr_mismatch_flag && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-yellow-400 bg-yellow-50 dark:bg-yellow-500/10 px-2 py-0.5 text-xs text-yellow-700 dark:text-yellow-300 font-medium">
                    <AlertTriangle className="w-3 h-3" />
                    OCR Mismatch
                  </span>
                )}
              </div>
              <p className="text-slate-500 dark:text-slate-400 text-sm mt-0.5 truncate">
                {blade.nomenclature} · {blade.part_number}
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 flex-wrap lg:justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate(`/blades/${id}/timeline`)}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              <History className="w-4 h-4" />
              Timeline
            </Button>

            {blade.status === "MEASUREMENTS_RECORDED" &&
              !blade.work_order_number &&
              hasRole(["OH_OPERATOR", "SUPER_ADMIN"]) && (
                <Button
                  size="sm"
                  onClick={() =>
                    transitionMutation.mutate({ to_status: "SENT_TO_ASSEMBLY" })
                  }
                  disabled={transitionMutation.isPending}
                  className="bg-violet-600 hover:bg-violet-500 text-white"
                >
                  <ArrowRight className="w-4 h-4" />
                  Send to Assembly
                </Button>
              )}

            {blade.status === "MEASUREMENTS_RECORDED" &&
              blade.work_order_number &&
              hasRole(["OH_OPERATOR", "SUPER_ADMIN"]) && (
                <div className="flex items-center gap-2 flex-wrap rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/40 px-3 py-1.5 text-xs text-amber-700 dark:text-amber-300 max-w-full">
                  <Package className="w-3.5 h-3.5 flex-shrink-0" />
                  <span>
                    Part of work order <span className="font-mono font-semibold mx-1">{blade.work_order_number}</span>
                    — send the full batch from OH Queue
                  </span>
                </div>
              )}

            {blade.status === "BALANCING_COMPLETED" &&
              hasRole(["ASSEMBLY_OPERATOR", "SUPER_ADMIN"]) && (
                <Button
                  size="sm"
                  onClick={() =>
                    transitionMutation.mutate({ to_status: "FINAL_VERIFICATION" })
                  }
                  disabled={transitionMutation.isPending}
                  className="bg-lime-600 hover:bg-lime-500 text-white"
                >
                  <CheckCircle2 className="w-4 h-4" />
                  Final Verification
                </Button>
              )}

            {blade.status === "REJECTED" && hasRole(["OH_OPERATOR", "SUPER_ADMIN"]) && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => transitionMutation.mutate({ to_status: "REOPENED" })}
                disabled={transitionMutation.isPending}
                className="border-2 border-amber-400 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-600/20"
              >
                <RotateCcw className="w-4 h-4" />
                Reopen
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 w-full px-4 sm:px-6 py-5 flex flex-col gap-5 overflow-y-auto">
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 items-start shrink-0">
          {/* Left: detail cards */}
          <div className="xl:col-span-2 space-y-6">
            {/* Blade identity */}
            <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
              <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
                <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-orange-500 flex items-center justify-center">
                    <FileText className="w-3.5 h-3.5 text-white" />
                  </div>
                  Blade Identity
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <dl className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
                  <InfoField label="Serial Number" value={<span className="font-mono">{blade.serial_number}</span>} />
                  <InfoField label="Melt Number" value={<span className="font-mono">{blade.melt_number}</span>} />
                  <InfoField label="Work Order" value={blade.work_order_number} />
                  <InfoField label="Shop Order" value={blade.shop_order_number} />
                  <InfoField label="Part Number" value={blade.part_number} />
                  <InfoField label="Nomenclature" value={blade.nomenclature} />
                  <InfoField label="Work Order Number" value={blade.work_order_number} />
                  <InfoField label="Engine Number" value={blade.engine_number} />
                  <InfoField label="Engine Hours" value={(blade as any).engine_hours} />
                  <InfoField label="Component Hours" value={(blade as any).component_hours} />
                  <InfoField
                    label="Blade Type"
                    value={
                      (blade as any).blade_type ? (
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold",
                            (blade as any).blade_type === "LPTR"
                              ? "bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300"
                              : "bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300"
                          )}
                        >
                          {(blade as any).blade_type}
                          <span className="ml-1 font-normal opacity-75 text-[10px]">
                            {(blade as any).blade_type === "LPTR"
                              ? "(Rocking+Creep)"
                              : "(Rocking only)"}
                          </span>
                        </span>
                      ) : null
                    }
                  />
                  <InfoField
                    label="Created"
                    value={format(parseISO(blade.created_at), "dd MMM yyyy HH:mm")}
                  />
                </dl>
              </CardContent>
            </Card>

            {/* Measurements */}
            {blade.measurements && blade.measurements.length > 0 && (
              <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
                  <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                    <div className="w-7 h-7 rounded-lg bg-blue-500 flex items-center justify-center">
                      <Ruler className="w-3.5 h-3.5 text-white" />
                    </div>
                    Latest Measurements
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4">
                  {(() => {
                    const m = blade.measurements?.[0];
                    if (!m) return null;
                    return (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
                          <InfoField
                            label="Weight"
                            value={m.weight_grams != null ? `${m.weight_grams} g` : null}
                          />
                          <InfoField
                            label="Static Moment"
                            value={
                              m.static_moment_gcm != null
                                ? `${m.static_moment_gcm} g·cm`
                                : null
                            }
                          />
                          <InfoField label="Rocking Value" value={m.rocking_value} />
                          {m.creep_value != null && (
                            <InfoField label="Creep Value" value={m.creep_value} />
                          )}
                          <InfoField
                            label="Type"
                            value={m.measurement_type.replace(/_/g, " ")}
                          />
                          <InfoField
                            label="Recorded"
                            value={formatDistanceToNow(parseISO(m.measured_at), {
                              addSuffix: true,
                            })}
                          />
                        </dl>
                        <div>
                          <p className="text-slate-500 dark:text-slate-400 text-xs font-medium uppercase tracking-wide mb-2">
                            Rocking vs Creep
                          </p>
                          <ResponsiveContainer width="100%" height={100}>
                            <BarChart data={measurementChartData} barSize={32}>
                              <CartesianGrid
                                strokeDasharray="3 3"
                                stroke="#e2e8f0"
                                className="dark:stroke-slate-700"
                              />
                              <XAxis dataKey="name" tick={{ fill: "#64748b", fontSize: 11 }} />
                              <YAxis tick={{ fill: "#64748b", fontSize: 11 }} />
                              <Tooltip
                                contentStyle={{
                                  backgroundColor: "#1e293b",
                                  border: "1px solid #334155",
                                  borderRadius: "6px",
                                  color: "#f1f5f9",
                                }}
                              />
                              <Bar dataKey="value">
                                {measurementChartData.map((entry, i) => (
                                  <rect key={i} fill={entry.fill} />
                                ))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    );
                  })()}
                </CardContent>
              </Card>
            )}

            {/* OCR Data */}
            {blade.ocr_serial_number && (
              <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
                  <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                    <div className="w-7 h-7 rounded-lg bg-violet-500 flex items-center justify-center">
                      <ScanLine className="w-3.5 h-3.5 text-white" />
                    </div>
                    OCR Data
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4">
                  <div className="flex flex-col sm:flex-row items-start gap-4">
                    <dl className="flex-1 min-w-0 space-y-2">
                      <InfoField
                        label="OCR Serial Number"
                        value={<span className="font-mono">{blade.ocr_serial_number}</span>}
                      />
                      <InfoField
                        label="Manual Serial Number"
                        value={<span className="font-mono">{blade.serial_number}</span>}
                      />
                    </dl>
                    {blade.ocr_mismatch_flag && (
                      <div className="flex items-center gap-2 rounded-xl bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-300 dark:border-yellow-500/30 px-3 py-2 text-sm text-yellow-700 dark:text-yellow-300 font-medium">
                        <AlertTriangle className="w-4 h-4 shrink-0" />
                        OCR/manual mismatch detected
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Slot allocation */}
            {blade.slot_allocation && (
              <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
                  <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                    <div className="w-7 h-7 rounded-lg bg-cyan-500 flex items-center justify-center">
                      <Package className="w-3.5 h-3.5 text-white" />
                    </div>
                    Slot Allocation
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4">
                  <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
                    <InfoField label="Slot Number" value={`#${blade.slot_allocation.slot_number}`} />
                    <InfoField
                      label="Balanced"
                      value={
                        blade.slot_allocation.is_balanced ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                        ) : (
                          <Clock className="w-5 h-5 text-amber-500" />
                        )
                      }
                    />
                    <InfoField
                      label="Allocated"
                      value={format(
                        parseISO(blade.slot_allocation.allocated_at),
                        "dd MMM yyyy"
                      )}
                    />
                  </dl>
                  {blade.slot_allocation.balancing_remarks && (
                    <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
                      <p className="text-slate-500 dark:text-slate-400 text-xs uppercase tracking-wide mb-1">
                        Balancing Remarks
                      </p>
                      <p className="text-slate-700 dark:text-slate-300 text-sm">
                        {blade.slot_allocation.balancing_remarks}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>

          {/* Right: workflow timeline */}
          <div className="xl:col-span-1">
            <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm sticky top-6">
              <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-700/50">
                <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-orange-500 flex items-center justify-center">
                    <History className="w-3.5 h-3.5 text-white" />
                  </div>
                  Workflow Timeline
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <ScrollArea className="max-h-[600px] pr-2">
                  {logs.length === 0 ? (
                    <div className="text-center py-8 text-slate-400 dark:text-slate-500 text-sm">
                      No workflow history yet
                    </div>
                  ) : (
                    <WorkflowTimeline logs={logs} />
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
