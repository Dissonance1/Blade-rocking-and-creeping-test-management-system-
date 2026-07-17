import { useEffect, useState } from "react";
import { useAuthStore } from "@/store/authStore";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
import { toast } from "sonner";
import {
  Package,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  Loader2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  ArrowRight,
  Send,
  Wrench,
  MapPin,
  ClipboardCheck,
  SlidersHorizontal,
  Scale,
} from "lucide-react";
import { BatchOverviewIcon } from "@/components/common/CustomIcons";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import KTIcon from "@/components/common/KTIcon";

import { batchService, type BatchSummary, type BatchStatus, type BatchEvent } from "@/services/batchService";
import { cn } from "@/utils/cn";

const REFRESH_TOAST_DURATION = 3000;

// ─── Refresh toast ────────────────────────────────────────────────────────────

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
          <p className="text-sm font-semibold text-slate-900 dark:text-white">Work order list refreshed</p>
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

// ─── KPI card ─────────────────────────────────────────────────────────────────

type KpiAccent = "slate" | "violet" | "emerald" | "rose";

const KPI_ACCENT: Record<KpiAccent, { gradient: string; glow: string }> = {
  slate:   { gradient: "from-slate-400 to-slate-600",       glow: "shadow-slate-500/30" },
  violet:  { gradient: "from-violet-400 to-violet-600",     glow: "shadow-violet-500/30" },
  emerald: { gradient: "from-emerald-400 to-emerald-600",   glow: "shadow-emerald-500/30" },
  rose:    { gradient: "from-rose-400 to-rose-600",         glow: "shadow-rose-500/30" },
};

function KpiCard({ title, value, icon, accent }: {
  title: string; value: number; icon: React.ReactNode; accent: KpiAccent;
}) {
  const a = KPI_ACCENT[accent];
  return (
    <div className="h-24 w-full rounded-2xl border border-white/60 dark:border-white/10 bg-white/70 dark:bg-background backdrop-blur-xl p-3.5 shadow-xl shadow-slate-200/50 dark:shadow-black/20 flex flex-col">
      <div className="flex items-center gap-2.5 min-w-0">
        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center bg-gradient-to-br shadow-lg text-white shrink-0", a.gradient, a.glow)}>
          {icon}
        </div>
        <p className="text-sm font-bold text-slate-900 dark:text-white truncate">{title}</p>
      </div>
      <p className="text-2xl font-semibold tabular-nums tracking-tight mt-auto text-slate-900 dark:text-white">{value}</p>
    </div>
  );
}

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  BatchStatus,
  { label: string; cls: string; icon: React.ReactNode }
> = {
  CREATED: {
    label: "Created",
    cls: "bg-slate-500 text-white",
    icon: <Package className="w-3 h-3" />,
  },
  MEASUREMENTS_RECORDED: {
    label: "Measurements Recorded",
    cls: "bg-indigo-500 text-white",
    icon: <ClipboardCheck className="w-3 h-3" />,
  },
  SENT_TO_ASSEMBLY: {
    label: "Sent to Assembly",
    cls: "bg-violet-500 text-white",
    icon: <Send className="w-3 h-3" />,
  },
  RECEIVED_BY_ASSEMBLY: {
    label: "Received by Assembly",
    cls: "bg-blue-500 text-white",
    icon: <CheckCircle2 className="w-3 h-3" />,
  },
  ACCEPTED: {
    label: "Accepted",
    cls: "bg-emerald-500 text-white",
    icon: <CheckCircle2 className="w-3 h-3" />,
  },
  REJECTED: {
    label: "Rejected",
    cls: "bg-red-500 text-white",
    icon: <XCircle className="w-3 h-3" />,
  },
  SLOTS_ALLOCATED: {
    label: "Slots Allocated",
    cls: "bg-cyan-500 text-white",
    icon: <MapPin className="w-3 h-3" />,
  },
  SET_MAKING: {
    label: "Set Making",
    cls: "bg-fuchsia-500 text-white",
    icon: <SlidersHorizontal className="w-3 h-3" />,
  },
  BALANCED: {
    label: "Balanced",
    cls: "bg-teal-500 text-white",
    icon: <Scale className="w-3 h-3" />,
  },
  MODIFIED: {
    label: "Modified",
    cls: "bg-amber-500 text-white",
    icon: <Wrench className="w-3 h-3" />,
  },
};

function StatusBadge({ status }: { status: BatchStatus }) {
  const cfg = STATUS_CONFIG[status] ?? { label: status, cls: "bg-slate-500 text-white", icon: null };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold",
        cfg.cls
      )}
    >
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

// ─── Modification changes renderer ────────────────────────────────────────────

function ModificationChanges({ changes }: { changes: Record<string, unknown> | null }) {
  if (!changes || Object.keys(changes).length === 0) return null;

  const FIELD_LABELS: Record<string, string> = {
    weight_grams: "Weight (g)",
    static_moment_gcm: "Static Moment (g·cm)",
    melt_number: "Melt No.",
  };

  return (
    <div className="mt-2 rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-700/40 p-2 space-y-1.5">
      <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">Blade changes:</p>
      {Object.entries(changes).map(([sn, bladeChanges]) => {
        const bc = bladeChanges as Record<string, { before: unknown; after: unknown }>;
        return (
          <div key={sn} className="text-xs">
            <span className="font-mono font-semibold text-orange-500 dark:text-orange-400">{sn}</span>
            <div className="ml-3 mt-0.5 space-y-0.5">
              {Object.entries(bc).map(([field, diff]) => (
                <div key={field} className="flex items-center gap-1 font-mono text-slate-600 dark:text-slate-300">
                  <span className="text-slate-400 dark:text-slate-500 text-xs">
                    {FIELD_LABELS[field] ?? field}:
                  </span>
                  <span className="line-through text-slate-400">{String(diff.before)}</span>
                  <ArrowRight className="w-3 h-3 text-slate-400 flex-shrink-0" />
                  <strong className="text-emerald-600 dark:text-emerald-400">{String(diff.after)}</strong>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Work order detail panel ─────────────────────────────────────────────────

function BatchDetailPanel({ workOrderNumber }: { workOrderNumber: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["batch", workOrderNumber],
    queryFn: () => batchService.get(workOrderNumber),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-slate-400 dark:text-slate-500" />
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="mt-3 space-y-3 border-t border-slate-100 dark:border-white/10 pt-3 max-h-56 overflow-y-auto">
      {/* Metadata row */}
      <div className="grid grid-cols-2 gap-3 text-xs">
        {data.work_order_number && (
          <div className="rounded-xl bg-slate-50/80 dark:bg-white/5 border border-slate-100 dark:border-white/10 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Work Order</p>
            <p className="font-semibold text-slate-900 dark:text-white mt-1 font-mono">{data.work_order_number}</p>
          </div>
        )}
        {data.part_number && (
          <div className="rounded-xl bg-slate-50/80 dark:bg-white/5 border border-slate-100 dark:border-white/10 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Part No.</p>
            <p className="font-semibold text-slate-900 dark:text-white mt-1 font-mono">{data.part_number}</p>
          </div>
        )}
        {data.engine_number && (
          <div className="rounded-xl bg-slate-50/80 dark:bg-white/5 border border-slate-100 dark:border-white/10 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Engine No.</p>
            <p className="font-semibold text-slate-900 dark:text-white mt-1 font-mono">{data.engine_number}</p>
          </div>
        )}
        {data.nomenclature && (
          <div className="rounded-xl bg-slate-50/80 dark:bg-white/5 border border-slate-100 dark:border-white/10 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Nomenclature</p>
            <p className="font-semibold text-slate-900 dark:text-white mt-1 truncate">{data.nomenclature}</p>
          </div>
        )}
      </div>

      {/* Event timeline */}
      <div className="pt-4 mt-4 border-t border-dashed border-slate-200 dark:border-white/10 space-y-3">
        <div className="flex items-center gap-3">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-widest shrink-0">
            Event History
          </p>
          <div className="flex-1 h-px bg-slate-100 dark:bg-white/5" />
        </div>
        {data.events.length === 0 ? (
          <p className="text-xs text-slate-400 dark:text-slate-500 italic py-2">No events recorded yet.</p>
        ) : (
          <div className="space-y-2.5">
            {data.events.map((ev: BatchEvent) => {
              const scfg = STATUS_CONFIG[ev.event_type as BatchStatus];
              return (
                <div
                  key={ev.id}
                  className="rounded-xl bg-slate-50/80 dark:bg-white/5 border border-slate-100 dark:border-white/10 p-3 text-xs"
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "mt-0.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold flex-shrink-0",
                        scfg?.cls ?? "bg-slate-500 text-white"
                      )}
                    >
                      {scfg?.icon}
                      {scfg?.label ?? ev.event_type}
                    </span>
                    <div className="flex-1 min-w-0">
                      {ev.remarks && (
                        <p className="text-slate-600 dark:text-slate-300">{ev.remarks}</p>
                      )}
                      <p className="text-slate-400 dark:text-slate-500 mt-0.5">
                        by {ev.action_by?.full_name ?? ev.action_by?.username ?? "System"}{" "}
                        · {formatDistanceToNow(parseISO(ev.timestamp), { addSuffix: true })}
                      </p>
                    </div>
                  </div>
                  {ev.event_type === "MODIFIED" && (
                    <ModificationChanges changes={ev.changes} />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Work order card (read-only) ─────────────────────────────────────────────

function BatchCard({ batch }: { batch: BatchSummary }) {
  const [expanded, setExpanded] = useState(false);
  // rows_complete_count = blades with Melt Number + Weight actually stored —
  // NOT blade_count, which is the fixed 90-row scaffold present from the
  // moment the Work Order is started, before any row is filled in.
  const filledPct = Math.round((batch.rows_complete_count / 90) * 100);
  const sentPct = Math.round((batch.blades_sent / 90) * 100);

  return (
    <Card className="bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20">
      <CardHeader className="pb-1 pt-3 px-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-sm font-semibold text-slate-900 dark:text-white font-mono truncate">
              {batch.work_order_number}
            </CardTitle>
            {batch.nomenclature && (
              <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                {batch.nomenclature}
              </p>
            )}
          </div>
          <StatusBadge status={batch.current_status} />
        </div>
      </CardHeader>

      <CardContent className="px-3.5 pb-3.5 space-y-2">
        {/* Blade progress bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-slate-500 dark:text-slate-400">
            <span>Blade entry progress</span>
            <span className={cn(batch.is_entry_complete ? "text-emerald-500 font-semibold" : "")}>
              {batch.rows_complete_count} / 90{batch.is_entry_complete ? " (Complete)" : ""}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/15 overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                batch.is_entry_complete
                  ? "bg-gradient-to-r from-emerald-400 to-emerald-600"
                  : "bg-gradient-to-r from-orange-400 to-orange-500"
              )}
              style={{ width: `${Math.min(filledPct, 100)}%` }}
            />
          </div>
        </div>

        {/* Sent bar */}
        {batch.blades_sent > 0 && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400">
              <span>Sent to Assembly</span>
              <span className="text-violet-500 font-semibold">{batch.blades_sent}</span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/15 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-violet-400 to-violet-600 transition-all"
                style={{ width: `${Math.min(sentPct, 100)}%` }}
              />
            </div>
          </div>
        )}

        {/* Timestamps */}
        <div className="flex gap-4 text-xs text-slate-400 dark:text-slate-500">
          {batch.first_blade_at && (
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              Created {formatDistanceToNow(parseISO(batch.first_blade_at), { addSuffix: true })}
            </span>
          )}
          {batch.first_sent_at && (
            <span className="flex items-center gap-1">
              <ArrowRight className="w-3 h-3" />
              Sent {formatDistanceToNow(parseISO(batch.first_sent_at), { addSuffix: true })}
            </span>
          )}
        </div>

        {/* Last event snippet */}
        {batch.last_event && (
          <div className="rounded-xl bg-slate-50/80 dark:bg-white/5 border border-slate-100 dark:border-white/10 p-2 text-xs text-slate-600 dark:text-slate-300">
            <span className="font-medium text-slate-400 dark:text-slate-500">Latest: </span>
            {batch.last_event.remarks ?? STATUS_CONFIG[batch.last_event.event_type as BatchStatus]?.label}
          </div>
        )}

        {/* Expand / collapse event history */}
        <Button
          variant="ghost"
          size="sm"
          className="w-full text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 h-7"
          onClick={() => setExpanded((p) => !p)}
        >
          {expanded ? (
            <>
              <ChevronUp className="w-3 h-3 mr-1" />
              Hide Events
            </>
          ) : (
            <>
              <ChevronDown className="w-3 h-3 mr-1" />
              Show Events
            </>
          )}
        </Button>

        {expanded && <BatchDetailPanel workOrderNumber={batch.work_order_number} />}
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BatchTrackingPage() {
  const hasRole = useAuthStore((s) => s.hasRole);

  // OH Operator, QA Viewer, and Super Admin all see the OH (701 Hanger) work order view.
  // Assembly Operator sees only work orders that have been sent/received at assembly.
  const isOHView = hasRole(["OH_OPERATOR", "QA_VIEWER", "SUPER_ADMIN"]);
  const isAssemblyView = hasRole(["ASSEMBLY_OPERATOR"]) && !hasRole(["SUPER_ADMIN"]);

  const { data: batches = [], isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  async function handleRefresh() {
    await refetch();
    toast.custom(() => <RefreshToast />, { duration: REFRESH_TOAST_DURATION, unstyled: true });
  }

  const statusOrder: Record<BatchStatus, number> = {
    CREATED: 0,
    MEASUREMENTS_RECORDED: 1,
    SENT_TO_ASSEMBLY: 2,
    RECEIVED_BY_ASSEMBLY: 3,
    MODIFIED: 4,
    ACCEPTED: 5,
    SLOTS_ALLOCATED: 6,
    SET_MAKING: 7,
    BALANCED: 8,
    REJECTED: 9,
  };

  const ASSEMBLY_STATUSES: BatchStatus[] = [
    "SENT_TO_ASSEMBLY",
    "RECEIVED_BY_ASSEMBLY",
    "MODIFIED",
    "ACCEPTED",
    "SLOTS_ALLOCATED",
    "REJECTED",
  ];

  // OH view: all work orders regardless of status
  // Assembly view: only work orders that crossed into assembly
  const sorted = [...batches]
    .filter((b) => isOHView || ASSEMBLY_STATUSES.includes(b.current_status))
    .sort((a, b) => (statusOrder[a.current_status] ?? 99) - (statusOrder[b.current_status] ?? 99));

  const total = sorted.length;
  const sent = sorted.filter((b) => b.current_status === "SENT_TO_ASSEMBLY").length;
  const accepted = sorted.filter((b) => b.current_status === "ACCEPTED").length;
  const rejected = sorted.filter((b) => b.current_status === "REJECTED").length;

  const pageTitle = isAssemblyView ? "Assembly Work Order Overview" : "OH Work Order Overview";
  const pageSubtitle = isAssemblyView
    ? "Work orders received at 720 Hanger (Assembly)"
    : "Work orders created and managed at 701 Hanger (OH)";

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">

      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <BatchOverviewIcon className="w-5 h-5 text-orange-500 shrink-0" />
              {pageTitle}
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight">
              {pageSubtitle}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={isFetching}
            className="w-full sm:w-auto sm:min-w-[8rem] h-8 justify-center border-2 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 gap-1.5"
          >
            <RefreshCw className={cn("w-3.5 h-3.5", isFetching && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="w-full px-4 sm:px-6 py-3 flex flex-col gap-3">

        {/* KPI row */}
        <div className="shrink-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <KpiCard
            title="Total Work Orders"
            value={total}
            icon={<Package className="w-5 h-5" />}
            accent="slate"
          />
          <KpiCard
            title="Sent to Assembly"
            value={sent}
            icon={<Send className="w-5 h-5" />}
            accent="violet"
          />
          <KpiCard
            title="Accepted"
            value={accepted}
            icon={<CheckCircle2 className="w-5 h-5" />}
            accent="emerald"
          />
          <KpiCard
            title="Rejected"
            value={rejected}
            icon={<XCircle className="w-5 h-5" />}
            accent="rose"
          />
        </div>

        {/* Work order grid */}
        <Card className="shrink-0 bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 overflow-hidden">
          <CardHeader className="shrink-0 pb-4 border-b border-slate-100 dark:border-slate-700/50">
            <CardTitle className="text-slate-900 dark:text-white text-lg flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-xl flex items-center justify-center bg-gradient-to-br from-teal-400 to-cyan-600 shadow-lg shadow-cyan-500/30 text-white">
                <KTIcon iconName="chart-line-up" className="text-base leading-none" />
              </span>
              All Work Orders
              {!isLoading && (
                <span className="text-sm font-normal text-slate-400 dark:text-slate-400">
                  ({sorted.length})
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-3">
            {isLoading ? (
              <div className="flex items-center justify-center h-full min-h-[12rem]">
                <Loader2 className="w-6 h-6 animate-spin text-slate-400 dark:text-slate-500" />
              </div>
            ) : isError ? (
              <div className="flex items-center justify-center gap-2 h-full min-h-[12rem] text-red-500 dark:text-red-400">
                <AlertCircle className="w-5 h-5" />
                <span>Failed to load work orders</span>
              </div>
            ) : sorted.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full min-h-[12rem] text-slate-400 dark:text-slate-500 gap-3">
                <Package className="w-10 h-10 opacity-40" />
                <p className="text-center text-sm max-w-sm">
                  No work orders found. Register blades with a work order number to get started.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 pb-1 items-start">
                {sorted.map((batch) => (
                  <BatchCard key={batch.work_order_number} batch={batch} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

    </div>
  );
}
