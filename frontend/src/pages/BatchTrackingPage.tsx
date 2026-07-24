import { useEffect, useMemo, useState } from "react";
import { useAuthStore } from "@/store/authStore";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { toast } from "sonner";
import {
  Package,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  ArrowRight,
  Send,
  Wrench,
  MapPin,
  ClipboardCheck,
  SlidersHorizontal,
  Scale,
  Undo2,
  Download,
  X,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { BatchOverviewIcon } from "@/components/common/CustomIcons";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import KTIcon from "@/components/common/KTIcon";

import {
  batchService,
  type BatchSummary,
  type BatchStatus,
  type BatchEvent,
  type BladeRockingCreepEntry,
} from "@/services/batchService";
import { reportService } from "@/services/reportService";
import { extractApiError } from "@/services/api";
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
  RETURNED_TO_OH: {
    label: "Returned to OH",
    cls: "bg-orange-500 text-white",
    icon: <Undo2 className="w-3 h-3" />,
  },
  ACCEPTED_BY_OH: {
    label: "Accepted by OH",
    cls: "bg-emerald-600 text-white",
    icon: <CheckCircle2 className="w-3 h-3" />,
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

// ─── Work order events dialog ────────────────────────────────────────────────

function WorkOrderEventsDialog({
  workOrderNumber,
  onClose,
}: {
  workOrderNumber: string | null;
  onClose: () => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["batch", workOrderNumber],
    queryFn: () => batchService.get(workOrderNumber!),
    enabled: !!workOrderNumber,
  });

  return (
    <Dialog open={!!workOrderNumber} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-mono text-slate-900 dark:text-white">
            {workOrderNumber}
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-slate-400 dark:text-slate-500" />
          </div>
        ) : !data ? null : (
          <div className="flex-1 min-h-0 space-y-3 overflow-y-auto">
            {/* Metadata row */}
            <div className="grid grid-cols-2 gap-3 text-xs">
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
            </div>

            {/* Event timeline */}
            <div className="pt-3 mt-3 border-t border-dashed border-slate-200 dark:border-white/10 space-y-3">
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
                    const ts = parseISO(ev.timestamp);
                    return (
                      <div
                        key={ev.id}
                        className="rounded-xl bg-slate-50/80 dark:bg-white/5 border border-slate-100 dark:border-white/10 p-3 text-xs"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <span
                            className={cn(
                              "mt-0.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold flex-shrink-0",
                              scfg?.cls ?? "bg-slate-500 text-white"
                            )}
                          >
                            {scfg?.icon}
                            {scfg?.label ?? ev.event_type}
                          </span>
                          <span className="text-right text-slate-400 dark:text-slate-500 shrink-0 whitespace-nowrap">
                            {format(ts, "dd MMM yyyy, HH:mm")}
                          </span>
                        </div>
                        <div className="mt-1.5">
                          {ev.remarks && (
                            <p className="text-slate-600 dark:text-slate-300">{ev.remarks}</p>
                          )}
                          <p className="text-slate-400 dark:text-slate-500 mt-0.5">
                            by {ev.action_by?.full_name ?? ev.action_by?.username ?? "System"}{" "}
                            · {formatDistanceToNow(ts, { addSuffix: true })}
                          </p>
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
        )}
      </DialogContent>
    </Dialog>
  );
}

// ─── Work order table (read-only) ────────────────────────────────────────────

function BatchTableRow({
  batch,
  showSentColumn,
  onSelect,
}: {
  batch: BatchSummary;
  showSentColumn: boolean;
  onSelect: (workOrderNumber: string) => void;
}) {
  // rows_complete_count = blades with Melt Number + Weight actually stored —
  // NOT blade_count, which is the fixed 90-row scaffold present from the
  // moment the Work Order is started, before any row is filled in.
  const filledPct = Math.round((batch.rows_complete_count / 90) * 100);

  return (
    <tr
      className="border-b border-slate-100 dark:border-white/10 last:border-b-0 hover:bg-slate-50/80 dark:hover:bg-white/5 cursor-pointer"
      onClick={() => onSelect(batch.work_order_number)}
    >
      <td className="px-3 py-2.5 font-mono text-sm font-semibold text-slate-900 dark:text-white whitespace-nowrap">
        {batch.work_order_number}
      </td>
      <td className="px-3 py-2.5">
        <StatusBadge status={batch.current_status} />
      </td>
      <td className="px-3 py-2.5 min-w-[9rem]">
        <div className="flex items-center gap-2">
          <div className="h-1.5 flex-1 rounded-full bg-slate-100 dark:bg-white/15 overflow-hidden">
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
          <span
            className={cn(
              "text-xs whitespace-nowrap",
              batch.is_entry_complete
                ? "text-emerald-500 font-semibold"
                : "text-slate-500 dark:text-slate-400"
            )}
          >
            {batch.rows_complete_count}/90
          </span>
        </div>
      </td>
      {showSentColumn && (
        <td className="px-3 py-2.5 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
          {batch.blades_sent > 0 ? (
            <span className="text-violet-500 font-semibold">{batch.blades_sent}</span>
          ) : (
            "—"
          )}
        </td>
      )}
      <td className="px-3 py-2.5 text-xs text-slate-400 dark:text-slate-500 whitespace-nowrap">
        {batch.first_blade_at
          ? formatDistanceToNow(parseISO(batch.first_blade_at), { addSuffix: true })
          : "—"}
      </td>
    </tr>
  );
}

const ROWS_PER_PAGE = 13;

/** Windowed page numbers around `current`, always including first/last, "…" for gaps. */
function pageWindow(current: number, total: number): (number | "…")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = new Set<number>([1, total, current, current - 1, current + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const result: (number | "…")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - (sorted[i - 1] as number) > 1) result.push("…");
    result.push(p);
  });
  return result;
}

function TablePager({
  page,
  totalPages,
  onPageChange,
  className,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className={cn("shrink-0 flex items-center justify-center gap-1 px-3 py-2 border-t border-slate-100 dark:border-white/10", className)}>
      <Button
        variant="outline"
        size="sm"
        className="h-7 w-7 p-0 text-slate-500 dark:text-slate-300"
        disabled={page === 1}
        onClick={() => onPageChange(page - 1)}
      >
        <ChevronLeft className="w-3.5 h-3.5" />
      </Button>
      {pageWindow(page, totalPages).map((p, i) =>
        p === "…" ? (
          <span key={`ellipsis-${i}`} className="px-1.5 text-xs text-slate-400 dark:text-slate-500">
            …
          </span>
        ) : (
          <Button
            key={p}
            variant={p === page ? "default" : "outline"}
            size="sm"
            className={cn(
              "h-7 w-7 p-0 text-xs",
              p === page
                ? "bg-orange-500 hover:bg-orange-600 text-white border-orange-500"
                : "text-slate-500 dark:text-slate-300"
            )}
            onClick={() => onPageChange(p)}
          >
            {p}
          </Button>
        )
      )}
      <Button
        variant="outline"
        size="sm"
        className="h-7 w-7 p-0 text-slate-500 dark:text-slate-300"
        disabled={page === totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        <ChevronRight className="w-3.5 h-3.5" />
      </Button>
    </div>
  );
}

function BatchTable({
  title,
  batches,
  emptyLabel,
  showSentColumn = true,
  onSelectWorkOrder,
}: {
  title: string;
  batches: BatchSummary[];
  emptyLabel: string;
  showSentColumn?: boolean;
  onSelectWorkOrder: (workOrderNumber: string) => void;
}) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(batches.length / ROWS_PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const pageRows = batches.slice((safePage - 1) * ROWS_PER_PAGE, safePage * ROWS_PER_PAGE);

  return (
    <Card className="h-full flex flex-col bg-white/70 dark:bg-background backdrop-blur-xl border border-white/60 dark:border-white/10 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-black/20 overflow-hidden">
      <CardHeader className="shrink-0 pb-4 border-b border-slate-100 dark:border-slate-700/50">
        <CardTitle className="text-slate-900 dark:text-white text-lg flex items-center gap-2.5">
          <span className="w-8 h-8 rounded-xl flex items-center justify-center bg-gradient-to-br from-teal-400 to-cyan-600 shadow-lg shadow-cyan-500/30 text-white">
            <KTIcon iconName="chart-line-up" className="text-base leading-none" />
          </span>
          {title}
          <span className="text-sm font-normal text-slate-400 dark:text-slate-400">
            ({batches.length})
          </span>
        </CardTitle>
      </CardHeader>
      {batches.length === 0 ? (
        <CardContent className="flex-1 flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 gap-2">
          <Package className="w-8 h-8 opacity-40" />
          <p className="text-center text-sm max-w-sm">{emptyLabel}</p>
        </CardContent>
      ) : (
        <CardContent className="flex-1 min-h-0 flex flex-col p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 dark:border-white/10 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                  <th className="px-3 py-2 whitespace-nowrap">Work Order</th>
                  <th className="px-3 py-2 whitespace-nowrap">Status</th>
                  <th className="px-3 py-2 whitespace-nowrap">Blade Entry</th>
                  {showSentColumn && <th className="px-3 py-2 whitespace-nowrap">Sent</th>}
                  <th className="px-3 py-2 whitespace-nowrap">Created</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((batch) => (
                  <BatchTableRow
                    key={batch.work_order_number}
                    batch={batch}
                    showSentColumn={showSentColumn}
                    onSelect={onSelectWorkOrder}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <TablePager page={safePage} totalPages={totalPages} onPageChange={setPage} className="mt-auto" />
        </CardContent>
      )}
    </Card>
  );
}

// ─── Final report row (accepted-return summary + preview + download) ──────────

function sortByPreviewSlot(entries: BladeRockingCreepEntry[]): BladeRockingCreepEntry[] {
  return [...entries].sort((a, b) => {
    if (!a.slot_number || !b.slot_number) return (a.slot_number ? -1 : 0) - (b.slot_number ? -1 : 0);
    const na = parseInt(a.slot_number, 10), nb = parseInt(b.slot_number, 10);
    return isNaN(na) || isNaN(nb) ? a.slot_number.localeCompare(b.slot_number) : na - nb;
  });
}

function FinalReportRow({
  summary,
  onDismiss,
}: {
  summary: BatchSummary;
  onDismiss: () => void;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const isLptr = summary.blade_type === "LPTR";

  const {
    data: previewEntries = [],
    isLoading: previewLoading,
    isError: previewIsError,
  } = useQuery({
    queryKey: ["batch-preview", summary.work_order_number],
    queryFn: () => batchService.getRockingCreep(summary.work_order_number),
    enabled: previewOpen,
    staleTime: 30_000,
  });

  const sortedPreview = useMemo(() => sortByPreviewSlot(previewEntries), [previewEntries]);

  const downloadMutation = useMutation({
    mutationFn: () => reportService.exportBatchReport(summary.work_order_number, "excel"),
    onError: (err: unknown) => toast.error(extractApiError(err)),
  });

  return (
    <div className="py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="font-mono text-sm font-semibold text-slate-700 dark:text-slate-200 block">
            {summary.work_order_number}
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400 truncate block">
            {summary.blade_count} {summary.blade_type ?? ""} blade(s) • Part {summary.part_number ?? "—"}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPreviewOpen((v) => !v)}
            className="border-emerald-300 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-700 dark:text-emerald-300 dark:hover:bg-emerald-900/30"
          >
            {previewOpen ? (
              <ChevronUp className="w-3.5 h-3.5 mr-1.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 mr-1.5" />
            )}
            Preview
          </Button>
          <Button
            size="sm"
            onClick={() => downloadMutation.mutate()}
            disabled={downloadMutation.isPending}
            className="bg-emerald-500 hover:bg-emerald-600 text-white"
          >
            {downloadMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
            ) : (
              <Download className="w-3.5 h-3.5 mr-1.5" />
            )}
            Download Final Report
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onDismiss}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 px-2"
          >
            <X className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {previewOpen && (
        <div className="mt-2 rounded-lg border border-emerald-200 dark:border-emerald-700/40 overflow-hidden">
          {previewLoading ? (
            <div className="flex items-center justify-center py-4 text-slate-400 dark:text-slate-500 text-sm gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading preview…
            </div>
          ) : previewIsError ? (
            <div className="py-4 text-center text-sm text-red-500 dark:text-red-400">
              Failed to load preview
            </div>
          ) : sortedPreview.length === 0 ? (
            <div className="py-4 text-center text-sm text-slate-400 dark:text-slate-500">
              No blade data found for this work order
            </div>
          ) : (
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-xs whitespace-nowrap">
                <thead className="bg-slate-800 dark:bg-background sticky top-0">
                  <tr>
                    {[
                      "Slot No.",
                      "Serial No.",
                      "Melt No.",
                      "Weight (g)",
                      "Static Moment",
                      "Rocking",
                      ...(isLptr ? ["Creep"] : []),
                    ].map((h) => (
                      <th
                        key={h}
                        className="text-left px-3 py-2 text-slate-100 font-semibold text-[10px] uppercase tracking-wide"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-emerald-100 dark:divide-emerald-800/30">
                  {sortedPreview.map((e) => (
                    <tr key={e.blade_id}>
                      <td className="px-3 py-1.5">{e.slot_number ?? "—"}</td>
                      <td className="px-3 py-1.5 font-mono">{e.serial_number}</td>
                      <td className="px-3 py-1.5 font-mono">{e.melt_number}</td>
                      <td className="px-3 py-1.5">{e.weight_grams ?? "—"}</td>
                      <td className="px-3 py-1.5">{e.static_moment_gcm ?? "—"}</td>
                      <td className="px-3 py-1.5">{e.rocking_value ?? "—"}</td>
                      {isLptr && <td className="px-3 py-1.5">{e.creep_value ?? "—"}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BatchTrackingPage() {
  const hasRole = useAuthStore((s) => s.hasRole);
  const qc = useQueryClient();
  const [selectedWorkOrder, setSelectedWorkOrder] = useState<string | null>(null);
  const [acceptedSummaries, setAcceptedSummaries] = useState<Record<string, BatchSummary>>({});

  // OH Operator, QA Viewer, and Super Admin all see the OH (701 Hanger) work order view.
  // Assembly Operator sees only work orders that have been sent/received at assembly.
  const isOHView = hasRole(["OH_OPERATOR", "QA_VIEWER", "SUPER_ADMIN"]);
  const isAssemblyView = hasRole(["ASSEMBLY_OPERATOR"]) && !hasRole(["SUPER_ADMIN"]);
  const canAcceptReturn = hasRole(["OH_OPERATOR", "SUPER_ADMIN"]);

  const { data: batches = [], isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  const returnedBatches = batches.filter(
    (b) => b.blade_type === "LPTR" && b.current_status === "RETURNED_TO_OH"
  );

  const acceptReturnMutation = useMutation({
    mutationFn: (workOrderNumber: string) => batchService.acceptReturn(workOrderNumber),
    onSuccess: (_res, workOrderNumber) => {
      const summary = returnedBatches.find((b) => b.work_order_number === workOrderNumber);
      if (summary) {
        setAcceptedSummaries((prev) => ({ ...prev, [workOrderNumber]: summary }));
      }
      qc.invalidateQueries({ queryKey: ["batches"] });
      toast.success(`Work Order ${workOrderNumber} accepted`);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to accept work order";
      toast.error(msg);
    },
  });

  function dismissAcceptedSummary(workOrderNumber: string) {
    setAcceptedSummaries((prev) => {
      const next = { ...prev };
      delete next[workOrderNumber];
      return next;
    });
  }

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
    RETURNED_TO_OH: 9,
    ACCEPTED_BY_OH: 10,
  };

  const ASSEMBLY_STATUSES: BatchStatus[] = [
    "SENT_TO_ASSEMBLY",
    "RECEIVED_BY_ASSEMBLY",
    "MODIFIED",
    "ACCEPTED",
    "SLOTS_ALLOCATED",
  ];

  // OH view: all work orders regardless of status.
  // Assembly view: LPTR-only, and only once it's crossed into assembly —
  // HPTR blades never leave OH (see state_machine.py), so even though HPTR
  // work orders pass through some of the same status values (e.g.
  // SLOTS_ALLOCATED is used by both LPTR's assembly-side and HPTR's OH-side
  // slot allocation), an Assembly user must never see HPTR batches at all.
  const sorted = [...batches]
    .filter((b) =>
      isOHView || (b.blade_type === "LPTR" && ASSEMBLY_STATUSES.includes(b.current_status))
    )
    .sort((a, b) => (statusOrder[a.current_status] ?? 99) - (statusOrder[b.current_status] ?? 99));

  // A Work Order is always exactly one blade_type — split into two tables
  // rather than a single mixed list/grid.
  const lptrBatches = sorted.filter((b) => b.blade_type === "LPTR");
  const hptrBatches = isAssemblyView ? [] : sorted.filter((b) => b.blade_type === "HPTR");

  const pageTitle = isAssemblyView ? "Assembly Work Order Overview" : "OH Work Order Overview";
  const pageSubtitle = isAssemblyView
    ? "Work orders received at 720 Hanger (Assembly)"
    : "Work orders created and managed at 701 Hanger (OH)";

  return (
    <div className="h-full flex flex-col overflow-hidden bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">

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

      <div className="flex-1 min-h-0 w-full px-4 sm:px-6 py-3 flex flex-col gap-3 overflow-hidden">
        {canAcceptReturn && returnedBatches.length > 0 && (
          <Card className="shrink-0 bg-orange-50/60 dark:bg-orange-900/10 border-orange-200 dark:border-orange-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2 text-orange-800 dark:text-orange-300">
                <Undo2 className="w-4 h-4 shrink-0" />
                Returned from Assembly — Needs Acceptance
                <span className="text-xs font-normal text-orange-600 dark:text-orange-400 bg-orange-100 dark:bg-orange-900/40 px-2 py-0.5 rounded-full">
                  {returnedBatches.length}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex flex-col divide-y divide-orange-200/70 dark:divide-orange-700/40">
                {returnedBatches.map((b) => (
                  <div
                    key={b.work_order_number}
                    className="flex items-center justify-between gap-3 py-2.5"
                  >
                    <span className="font-mono text-sm font-semibold text-slate-700 dark:text-slate-200">
                      {b.work_order_number}
                    </span>
                    <Button
                      size="sm"
                      onClick={() => acceptReturnMutation.mutate(b.work_order_number)}
                      disabled={acceptReturnMutation.isPending}
                      className="bg-emerald-500 hover:bg-emerald-600 text-white"
                    >
                      {acceptReturnMutation.isPending ? (
                        <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />
                      )}
                      Accept
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {Object.keys(acceptedSummaries).length > 0 && (
          <Card className="shrink-0 bg-emerald-50/60 dark:bg-emerald-900/10 border-emerald-200 dark:border-emerald-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2 text-emerald-800 dark:text-emerald-300">
                <Download className="w-4 h-4 shrink-0" />
                Final Report Ready
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex flex-col divide-y divide-emerald-200/70 dark:divide-emerald-700/40">
                {Object.values(acceptedSummaries).map((s) => (
                  <FinalReportRow
                    key={s.work_order_number}
                    summary={s}
                    onDismiss={() => dismissAcceptedSummary(s.work_order_number)}
                  />
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center min-h-[12rem]">
            <Loader2 className="w-6 h-6 animate-spin text-slate-400 dark:text-slate-500" />
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center gap-2 min-h-[12rem] text-red-500 dark:text-red-400">
            <AlertCircle className="w-5 h-5" />
            <span>Failed to load work orders</span>
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center min-h-[12rem] text-slate-400 dark:text-slate-500 gap-3">
            <Package className="w-10 h-10 opacity-40" />
            <p className="text-center text-sm max-w-sm">
              No work orders found. Register blades with a work order number to get started.
            </p>
          </div>
        ) : (
          <div className={cn("flex-1 min-h-0 grid grid-cols-1 gap-3", !isAssemblyView && "lg:grid-cols-2")}>
            <BatchTable
              title="LPTR Work Orders"
              batches={lptrBatches}
              emptyLabel="No LPTR work orders found."
              onSelectWorkOrder={setSelectedWorkOrder}
            />
            {/* HPTR blades never leave OH — Assembly users never see this table. */}
            {!isAssemblyView && (
              <BatchTable
                title="HPTR Work Orders"
                batches={hptrBatches}
                emptyLabel="No HPTR work orders found."
                showSentColumn={false}
                onSelectWorkOrder={setSelectedWorkOrder}
              />
            )}
          </div>
        )}
      </div>

      <WorkOrderEventsDialog
        workOrderNumber={selectedWorkOrder}
        onClose={() => setSelectedWorkOrder(null)}
      />
    </div>
  );
}
