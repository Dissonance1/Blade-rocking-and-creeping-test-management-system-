import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Printer,
  FileDown,
  Loader2,
  History,
  User,
  MapPin,
  Clock,
} from "lucide-react";
import { format, parseISO, formatDistanceToNow } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";

import { bladeService } from "@/services/bladeService";
import { workflowService } from "@/services/workflowService";
import type { BladeStatus, WorkflowLog } from "@/types";
import { cn } from "@/utils/cn";

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CFG: Record<BladeStatus, { label: string; color: string; ring: string }> = {
  CREATED: { label: "Created", color: "bg-indigo-500", ring: "ring-indigo-200 dark:ring-indigo-500/30" },
  OH_INSPECTION: { label: "OH Inspection", color: "bg-amber-500", ring: "ring-amber-200 dark:ring-amber-500/30" },
  MEASUREMENTS_RECORDED: { label: "Measurements Recorded", color: "bg-blue-500", ring: "ring-blue-200 dark:ring-blue-500/30" },
  SENT_TO_ASSEMBLY: { label: "Sent to Assembly", color: "bg-violet-500", ring: "ring-violet-200 dark:ring-violet-500/30" },
  ASSEMBLY_RECEIVED: { label: "Received at Assembly", color: "bg-blue-500", ring: "ring-blue-200 dark:ring-blue-500/30" },
  ASSEMBLY_VERIFIED: { label: "Assembly Verified", color: "bg-emerald-600", ring: "ring-emerald-200 dark:ring-emerald-600/30" },
  SLOT_ASSIGNED: { label: "Slot Assigned", color: "bg-cyan-500", ring: "ring-cyan-200 dark:ring-cyan-500/30" },
  BALANCING_IN_PROGRESS: { label: "Balancing In Progress", color: "bg-orange-500", ring: "ring-orange-200 dark:ring-orange-500/30" },
  BALANCING_COMPLETED: { label: "Balancing Completed", color: "bg-emerald-500", ring: "ring-emerald-200 dark:ring-emerald-500/30" },
  RETURNED_TO_OH: { label: "Returned to OH", color: "bg-amber-500", ring: "ring-amber-200 dark:ring-amber-500/30" },
  FINAL_VERIFICATION: { label: "Final Verification", color: "bg-lime-500", ring: "ring-lime-200 dark:ring-lime-500/30" },
  COMPLETED: { label: "Completed", color: "bg-green-500", ring: "ring-green-200 dark:ring-green-500/30" },
  REJECTED: { label: "Rejected", color: "bg-red-500", ring: "ring-red-200 dark:ring-red-500/30" },
  ON_HOLD: { label: "On Hold", color: "bg-slate-500", ring: "ring-slate-200 dark:ring-slate-500/30" },
  REOPENED: { label: "Reopened", color: "bg-amber-500", ring: "ring-amber-200 dark:ring-amber-500/30" },
};

// ─── Event card ───────────────────────────────────────────────────────────────

function TimelineEvent({
  log,
  isFirst,
  isLast,
}: {
  log: WorkflowLog;
  isFirst: boolean;
  isLast: boolean;
}) {
  const toCfg = STATUS_CFG[log.to_status];
  const fromCfg = log.from_status ? STATUS_CFG[log.from_status] : null;
  // Guard: action_by_id may be a UUID string or null
  const actorName = log.action_by_id ?? "";
  const actorInitials = actorName
    ? actorName.slice(0, 2).toUpperCase()
    : "?";

  return (
    <li className="flex gap-4 pb-8 last:pb-0">
      {/* Left column: dot + connector line */}
      <div className="flex flex-col items-center shrink-0 pt-1">
        <div
          className={cn(
            "w-10 h-10 rounded-full flex items-center justify-center ring-4 shrink-0 z-10",
            toCfg.color,
            toCfg.ring
          )}
        >
          <History className="w-4 h-4 text-white" />
        </div>
        {!isLast && (
          <div className="w-0.5 flex-1 bg-slate-300 dark:bg-slate-600 mt-2" />
        )}
      </div>

      {/* Right column: card */}
      <div className="flex-1 min-w-0 pb-2">
      <div
        className={cn(
          "rounded-xl border p-5 transition-colors",
          isFirst
            ? "bg-orange-50 dark:bg-slate-700/50 border-orange-200 dark:border-slate-600"
            : "bg-white dark:bg-slate-800/40 border-slate-200 dark:border-slate-700/50"
        )}
      >
        {/* Status transition */}
        <div className="flex items-center gap-2 flex-wrap mb-3">
          {fromCfg && (
            <>
              <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-700 px-2.5 py-1 text-xs font-medium text-slate-700 dark:text-slate-300">
                {fromCfg.label}
              </span>
              <ArrowRight className="w-4 h-4 text-slate-400 dark:text-slate-500 shrink-0" />
            </>
          )}
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold text-white",
              toCfg.color
            )}
          >
            {toCfg.label}
          </span>
          {isFirst && (
            <span className="ml-auto rounded-full bg-orange-500 text-white px-2 py-0.5 text-xs font-semibold">
              Current
            </span>
          )}
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-5 flex-wrap">
          {/* Actor */}
          <div className="flex items-center gap-2">
            <Avatar className="w-7 h-7">
              <AvatarFallback className="bg-slate-700 dark:bg-slate-600 text-white text-xs font-semibold">
                {actorInitials}
              </AvatarFallback>
            </Avatar>
            <div>
              <p className="text-slate-900 dark:text-white text-sm font-medium leading-none">{actorName}</p>
              <p className="text-slate-400 dark:text-slate-500 text-xs mt-0.5 flex items-center gap-1">
                <User className="w-3 h-3" /> Actor
              </p>
            </div>
          </div>

          <Separator orientation="vertical" className="h-8 bg-slate-200 dark:bg-slate-700" />

          {/* Station */}
          {log.station_id && (
            <>
              <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-400 text-sm">
                <MapPin className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                {log.station_id}
              </div>
              <Separator orientation="vertical" className="h-8 bg-slate-200 dark:bg-slate-700" />
            </>
          )}

          {/* Timestamp */}
          <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-400 text-sm">
            <Clock className="w-4 h-4 text-slate-400 dark:text-slate-500" />
            <div>
              <p>{format(parseISO(log.timestamp), "dd MMM yyyy, HH:mm")}</p>
              <p className="text-slate-400 dark:text-slate-500 text-xs">
                {formatDistanceToNow(parseISO(log.timestamp), { addSuffix: true })}
              </p>
            </div>
          </div>
        </div>

        {/* Remarks */}
        {log.remarks && (
          <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700/50">
            <p className="text-slate-600 dark:text-slate-400 text-sm italic">"{log.remarks}"</p>
          </div>
        )}
      </div>
      </div>  {/* close flex-1 wrapper */}
    </li>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function WorkflowTimelinePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: blade, isLoading: loadingBlade } = useQuery({
    queryKey: ["blade", id],
    queryFn: () => bladeService.get(id!),
    enabled: !!id,
  });

  const { data: history, isLoading: loadingHistory } = useQuery({
    queryKey: ["blade-history", id],
    queryFn: () => workflowService.getTransitions(id!),
    enabled: !!id,
  });

  const logs: WorkflowLog[] = history?.logs ?? [];
  const isLoading = loadingBlade || loadingHistory;

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white print:bg-white print:text-black">
      {/* Header — hidden in print */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm print:hidden">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(-1)}
              className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
            >
              <ArrowLeft className="w-4 h-4" />
            </Button>
            <div>
              <h1 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <History className="w-5 h-5 text-orange-500" />
                Workflow Timeline
              </h1>
              {blade && (
                <p className="text-slate-500 dark:text-slate-400 text-sm font-mono">{blade.serial_number}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.print()}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              <Printer className="w-4 h-4" />
              Print
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
              onClick={() => {
                // PDF export — in production use jsPDF or react-pdf
                window.print();
              }}
            >
              <FileDown className="w-4 h-4" />
              Export PDF
            </Button>
          </div>
        </div>
      </div>

      {/* Print header */}
      <div className="hidden print:block px-6 py-4 border-b">
        <h1 className="text-2xl font-bold">
          Workflow Timeline — {blade?.serial_number}
        </h1>
        <p className="text-sm text-slate-600">
          Blade Rocking &amp; Creep Test System · Printed{" "}
          {format(new Date(), "dd MMM yyyy HH:mm")}
        </p>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-8">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-orange-500" />
          </div>
        ) : (
          <>
            {/* Blade summary */}
            {blade && (
              <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm mb-8 print:bg-white print:border-slate-200">
                <CardHeader className="pb-2 border-b border-slate-100 dark:border-slate-700/50">
                  <CardTitle className="text-slate-900 dark:text-white text-sm font-semibold print:text-black">
                    Blade Summary
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 text-sm">
                    {[
                      ["Serial", blade.serial_number],
                      ["Melt", blade.melt_number],
                      ["Part", blade.part_number],
                      ["Work Order", blade.work_order_number],
                      ["Status", STATUS_CFG[blade.status]?.label ?? blade.status],
                      [
                        "Created",
                        format(parseISO(blade.created_at), "dd MMM yyyy"),
                      ],
                    ].map(([k, v]) => (
                      <div key={k}>
                        <span className="text-slate-500 dark:text-slate-400 print:text-slate-500">{k}: </span>
                        <span className="text-slate-900 dark:text-white font-medium print:text-black font-mono">
                          {v}
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Timeline */}
            {logs.length === 0 ? (
              <div className="text-center py-16 text-slate-400 dark:text-slate-500">
                <History className="w-12 h-12 mx-auto mb-3 opacity-20" />
                <p>No workflow events recorded yet</p>
              </div>
            ) : (
              <ol className="relative">
                {logs.map((log, idx) => (
                  <TimelineEvent
                    key={log.id}
                    log={log}
                    isFirst={idx === 0}
                    isLast={idx === logs.length - 1}
                  />
                ))}
              </ol>
            )}
          </>
        )}
      </div>
    </div>
  );
}
