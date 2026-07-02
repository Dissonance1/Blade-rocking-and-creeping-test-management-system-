
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Loader2, AlertCircle } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { cn } from "@/utils/cn";
import type { BladeStatus, BladeListItem } from "@/types";

const STATUS_CLS: Partial<Record<BladeStatus, string>> = {
  SENT_TO_ASSEMBLY: "bg-violet-500 text-white",
  SLOT_ASSIGNED: "bg-cyan-500 text-white",
  BALANCING_IN_PROGRESS: "bg-orange-500 text-white",
  BALANCING_COMPLETED: "bg-emerald-500 text-white",
};

function SplitBladeTable({ blades }: { blades: BladeListItem[] }) {
  const half = Math.ceil(blades.length / 2);
  const left = blades.slice(0, half);
  const right = blades.slice(half);

  const cols = ["#", "Serial", "Melt No.", "Wt (g)", "SM (g·cm)", "Status"];

  const renderHalf = (rows: BladeListItem[], offset: number) => (
    <table className="w-full text-xs">
      <thead className="bg-slate-800 dark:bg-slate-700">
        <tr>
          {cols.map((h) => (
            <th
              key={h}
              className="px-3 py-2.5 text-slate-100 font-semibold text-xs uppercase tracking-wide text-left whitespace-nowrap"
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
        {rows.map((blade, idx) => (
          <tr
            key={blade.id}
            className={cn(
              "transition-colors hover:bg-blue-50 dark:hover:bg-slate-700/30",
              idx % 2 === 0 ? "bg-white dark:bg-slate-800/40" : "bg-slate-50 dark:bg-slate-800/20"
            )}
          >
            <td className="px-3 py-2 text-slate-400 tabular-nums">{offset + idx + 1}</td>
            <td className="px-3 py-2 font-mono font-medium text-orange-500 dark:text-orange-400">
              {blade.serial_number}
            </td>
            <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">
              {blade.melt_number}
            </td>
            <td className="px-3 py-2 font-mono tabular-nums text-slate-700 dark:text-slate-200 font-medium">
              {blade.weight_grams != null ? blade.weight_grams.toFixed(2) : "—"}
            </td>
            <td className="px-3 py-2 font-mono tabular-nums text-slate-700 dark:text-slate-200 font-medium">
              {blade.static_moment_gcm != null ? blade.static_moment_gcm.toFixed(2) : "—"}
            </td>
            <td className="px-3 py-2">
              <span
                className={cn(
                  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
                  STATUS_CLS[blade.status] ?? "bg-slate-500 text-white"
                )}
              >
                {blade.status.replace(/_/g, " ")}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <div className="grid grid-cols-2 divide-x divide-slate-200 dark:divide-slate-700 overflow-hidden">
      <div className="overflow-x-auto">{renderHalf(left, 0)}</div>
      <div className="overflow-x-auto">{renderHalf(right, half)}</div>
    </div>
  );
}

export default function AcceptBatchPage() {
  const { batchNumber } = useParams<{ batchNumber: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: bladesData, isLoading } = useQuery({
    queryKey: ["blades", "accept-page", batchNumber],
    queryFn: () => bladeService.list({ batch_number: batchNumber!, limit: 200 }),
    enabled: !!batchNumber,
    staleTime: 30_000,
  });

  const batchBlades = bladesData?.items ?? [];

  const acceptMutation = useMutation({
    mutationFn: () => batchService.accept(batchNumber!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      queryClient.invalidateQueries({ queryKey: ["blades"] });
      toast.success(`Batch ${batchNumber} accepted — OH has been notified`);
      navigate("/assembly-queue");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to accept batch";
      toast.error(msg);
    },
  });

  if (!batchNumber) return null;

  return (
    <div className="max-w-screen-xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/assembly-queue")}
          className="mt-1 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 flex-shrink-0"
        >
          <ArrowLeft className="w-4 h-4 mr-1.5" />
          Back to Queue
        </Button>
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            Accept Batch{" "}
            <span className="font-mono text-orange-500">{batchNumber}</span>
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Review all blade details, then confirm acceptance. Slot assignment is done in the Slot Allocation page.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-32">
          <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        </div>
      ) : batchBlades.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-32 text-slate-400 dark:text-slate-500 gap-3">
          <AlertCircle className="w-8 h-8 opacity-50" />
          <p>No blades found for batch {batchNumber}.</p>
          <Button variant="outline" size="sm" onClick={() => navigate("/assembly-queue")}>
            Back to Queue
          </Button>
        </div>
      ) : (
        <>
          {/* Split blade details table */}
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
              <h2 className="font-semibold text-slate-900 dark:text-white text-sm">Blade Details</h2>
              <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">
                {batchBlades.length} blade{batchBlades.length !== 1 ? "s" : ""}
              </span>
            </div>
            <SplitBladeTable blades={batchBlades} />
          </div>

          {/* Confirm accept */}
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div>
              <p className="font-semibold text-slate-900 dark:text-white">
                Ready to accept this batch?
              </p>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
                This will mark{" "}
                <span className="font-mono text-orange-500">{batchNumber}</span>{" "}
                as accepted and notify OH. Then go to{" "}
                <strong>Slot Allocation</strong> to assign disc slots.
              </p>
            </div>
            <div className="flex gap-3 flex-shrink-0">
              <Button
                variant="outline"
                onClick={() => navigate("/assembly-queue")}
                className="border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300"
              >
                Cancel
              </Button>
              <Button
                onClick={() => acceptMutation.mutate()}
                disabled={acceptMutation.isPending}
                className="bg-emerald-600 hover:bg-emerald-500 text-white"
              >
                {acceptMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                )}
                Confirm Accept
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
