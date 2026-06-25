import { useState } from "react";
import { useAuthStore } from "@/store/authStore";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
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
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { batchService, type BatchSummary, type BatchStatus, type BatchEvent } from "@/services/batchService";
import { cn } from "@/utils/cn";

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

// ─── Batch detail panel ───────────────────────────────────────────────────────

function BatchDetailPanel({ batchNumber }: { batchNumber: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["batch", batchNumber],
    queryFn: () => batchService.get(batchNumber),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="mt-4 space-y-4">
      {/* Metadata row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        {data.work_order_number && (
          <div className="rounded-lg bg-slate-50 dark:bg-slate-700/30 p-2">
            <p className="text-slate-400 dark:text-slate-500">Work Order</p>
            <p className="font-medium text-slate-900 dark:text-white">{data.work_order_number}</p>
          </div>
        )}
        {data.part_number && (
          <div className="rounded-lg bg-slate-50 dark:bg-slate-700/30 p-2">
            <p className="text-slate-400 dark:text-slate-500">Part No.</p>
            <p className="font-medium text-slate-900 dark:text-white">{data.part_number}</p>
          </div>
        )}
        {data.engine_number && (
          <div className="rounded-lg bg-slate-50 dark:bg-slate-700/30 p-2">
            <p className="text-slate-400 dark:text-slate-500">Engine No.</p>
            <p className="font-medium text-slate-900 dark:text-white">{data.engine_number}</p>
          </div>
        )}
        {data.nomenclature && (
          <div className="rounded-lg bg-slate-50 dark:bg-slate-700/30 p-2">
            <p className="text-slate-400 dark:text-slate-500">Nomenclature</p>
            <p className="font-medium text-slate-900 dark:text-white truncate">{data.nomenclature}</p>
          </div>
        )}
      </div>

      {/* Event timeline */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
          Event History
        </p>
        {data.events.length === 0 ? (
          <p className="text-xs text-slate-400 dark:text-slate-500 italic">No events recorded yet.</p>
        ) : (
          <div className="space-y-2">
            {data.events.map((ev: BatchEvent) => {
              const scfg = STATUS_CONFIG[ev.event_type as BatchStatus];
              return (
                <div
                  key={ev.id}
                  className="rounded-lg bg-slate-50 dark:bg-slate-700/30 p-2.5 text-xs"
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

// ─── Batch card (read-only) ───────────────────────────────────────────────────

function BatchCard({ batch }: { batch: BatchSummary }) {
  const [expanded, setExpanded] = useState(false);
  const filledPct = Math.round((batch.blade_count / 90) * 100);
  const sentPct = Math.round((batch.blades_sent / 90) * 100);

  return (
    <Card className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base font-semibold text-slate-900 dark:text-white font-mono">
              {batch.batch_number}
            </CardTitle>
            {batch.nomenclature && (
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                {batch.nomenclature}
              </p>
            )}
          </div>
          <StatusBadge status={batch.current_status} />
        </div>
      </CardHeader>

      <CardContent className="px-4 pb-4 space-y-3">
        {/* Blade progress bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>Blades in batch</span>
            <span className={cn(batch.blade_count >= 90 ? "text-emerald-500 font-semibold" : "")}>
              {batch.blade_count} / 90{batch.blade_count >= 90 ? " (Full)" : ""}
            </span>
          </div>
          <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                batch.blade_count >= 90 ? "bg-emerald-500" : "bg-orange-400"
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
            <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
              <div
                className="h-full rounded-full bg-violet-500 transition-all"
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
          <div className="rounded-lg bg-slate-50 dark:bg-slate-700/30 p-2 text-xs text-slate-600 dark:text-slate-300">
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

        {expanded && <BatchDetailPanel batchNumber={batch.batch_number} />}
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BatchTrackingPage() {
  const queryClient = useQueryClient();
  const hasRole = useAuthStore((s) => s.hasRole);
  const isOH = hasRole(["OH_OPERATOR", "SUPER_ADMIN"]);

  const { data: batches = [], isLoading, isError } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  const statusOrder: Record<BatchStatus, number> = {
    SENT_TO_ASSEMBLY: 0,
    RECEIVED_BY_ASSEMBLY: 1,
    MODIFIED: 2,
    CREATED: 3,
    ACCEPTED: 4,
    REJECTED: 5,
  };
  const ASSEMBLY_STATUSES: BatchStatus[] = [
    "SENT_TO_ASSEMBLY",
    "RECEIVED_BY_ASSEMBLY",
    "MODIFIED",
    "ACCEPTED",
    "REJECTED",
  ];

  // OH users see all their batches; Assembly users see only batches sent to them
  const sorted = [...batches]
    .filter((b) => isOH || ASSEMBLY_STATUSES.includes(b.current_status))
    .sort((a, b) => (statusOrder[a.current_status] ?? 99) - (statusOrder[b.current_status] ?? 99));

  const total = sorted.length;
  const sent = sorted.filter((b) => b.current_status === "SENT_TO_ASSEMBLY").length;
  const accepted = sorted.filter((b) => b.current_status === "ACCEPTED").length;
  const rejected = sorted.filter((b) => b.current_status === "REJECTED").length;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Batch Overview</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Monitor batch status across OH and Assembly
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => queryClient.invalidateQueries({ queryKey: ["batches"] })}
          className="border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300"
        >
          <RefreshCw className="w-4 h-4 mr-1.5" />
          Refresh
        </Button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total Batches", value: total, cls: "from-slate-600 to-slate-700" },
          { label: "Sent to Assembly", value: sent, cls: "from-violet-600 to-violet-700" },
          { label: "Accepted", value: accepted, cls: "from-emerald-600 to-emerald-700" },
          { label: "Rejected", value: rejected, cls: "from-red-600 to-red-700" },
        ].map((s) => (
          <div
            key={s.label}
            className={cn(
              "rounded-xl p-4 text-white shadow-md bg-gradient-to-br",
              s.cls
            )}
          >
            <p className="text-white/70 text-xs font-medium">{s.label}</p>
            <p className="text-3xl font-bold tabular-nums mt-1">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Batch grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        </div>
      ) : isError ? (
        <div className="flex items-center justify-center gap-2 py-16 text-red-500">
          <AlertCircle className="w-5 h-5" />
          <span>Failed to load batches</span>
        </div>
      ) : sorted.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 gap-3">
          <Package className="w-10 h-10 opacity-40" />
          <p>No batches found. Register blades with a batch number to get started.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {sorted.map((batch) => (
            <BatchCard key={batch.batch_number} batch={batch} />
          ))}
        </div>
      )}
    </div>
  );
}
