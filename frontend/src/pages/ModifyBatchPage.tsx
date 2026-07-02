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
    <div className="max-w-5xl mx-auto space-y-6">
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
            Modify Batch{" "}
            <span className="font-mono text-orange-500">{batchNumber}</span>
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Click <strong>Edit</strong> on any blade row to correct its measurements, stage changes, then submit with a remark.
          </p>
        </div>
      </div>

      {/* Content */}
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
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
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
  );
}
