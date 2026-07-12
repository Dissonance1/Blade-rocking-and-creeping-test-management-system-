import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, AlertCircle } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { bladeService } from "@/services/bladeService";
import { batchService } from "@/services/batchService";
import { ModifyBladesPanel, type ModifySubmitData } from "@/components/ModifyBladesPanel";

export default function ModifyBatchPage() {
  const { batchNumber } = useParams<{ batchNumber: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: bladesData, isLoading } = useQuery({
    queryKey: ["blades", "modify-page", batchNumber],
    queryFn: () => bladeService.list({ batch_number: batchNumber!, limit: 200 }),
    enabled: !!batchNumber,
    staleTime: 30_000,
  });

  const batchBlades = bladesData?.items ?? [];

  const modifyMutation = useMutation({
    mutationFn: ({ modifications, remarks }: ModifySubmitData) =>
      batchService.modify(batchNumber!, modifications, remarks),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      queryClient.invalidateQueries({ queryKey: ["blades"] });
      toast.success(`Batch ${batchNumber} — Modifications saved. Now assign slots and accept.`);
      navigate(`/batches/${batchNumber}/accept`);
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to save modifications";
      toast.error(msg);
    },
  });

  if (!batchNumber) return null;

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background py-2.5">
        <div className="max-w-screen-xl mx-auto w-full px-4 sm:px-6 relative flex flex-col sm:flex-row items-center justify-center min-h-[44px]">
          <div className="sm:absolute sm:left-6 sm:top-1/2 sm:-translate-y-1/2 self-start sm:self-auto mb-2 sm:mb-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/assembly-queue")}
              className="text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 -ml-3 sm:ml-0"
            >
              <ArrowLeft className="w-4 h-4 mr-1.5" />
              Back to Queue
            </Button>
          </div>
          <div className="min-w-0 text-center flex flex-col items-center">
            <h1 className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white truncate">
              Modify Batch{" "}
              <span className="font-mono text-orange-500">{batchNumber}</span>
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
              Click <strong>Edit</strong> on any blade row to correct its measurements, stage changes, then submit with a remark.
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 w-full px-4 sm:px-6 pt-5 pb-16 flex flex-col gap-5">
        <div className="max-w-4xl mx-auto w-full">
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
            <div className="bg-white dark:bg-background rounded-xl border border-slate-200 dark:border-slate-700 p-4 sm:p-6 shadow-sm">
              <ModifyBladesPanel
                fullPage
                batchNumber={batchNumber}
                blades={batchBlades}
                onSubmit={(data) => modifyMutation.mutate(data)}
                onCancel={() => navigate("/assembly-queue")}
                isSubmitting={modifyMutation.isPending}
              />
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
