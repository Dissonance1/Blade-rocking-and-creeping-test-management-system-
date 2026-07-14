import { AlertCircle, ArrowRight, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { WorkOrderCompleteValidationError } from "@/services/workOrderService";

export default function CompleteWorkOrderDialog({
  open,
  errors,
  submitting,
  onJumpToRow,
  onClose,
  onRetry,
}: {
  open: boolean;
  errors: WorkOrderCompleteValidationError | null;
  submitting: boolean;
  onJumpToRow: (sNo: number) => void;
  onClose: () => void;
  onRetry: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-600 dark:text-red-400">
            <AlertCircle className="w-5 h-5" />
            Work Order cannot be completed
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3 max-h-96 overflow-y-auto">
          {errors?.incomplete_rows && errors.incomplete_rows.length > 0 && (
            <div>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-1.5">
                {errors.incomplete_rows.length} row(s) missing Melt Number or Weight:
              </p>
              <div className="flex flex-wrap gap-1.5">
                {errors.incomplete_rows.map((sNo) => (
                  <button
                    key={sNo}
                    type="button"
                    onClick={() => onJumpToRow(sNo)}
                    className="inline-flex items-center gap-1 text-xs font-mono rounded-full px-2 py-1 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700/50 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30"
                  >
                    Row {String(sNo).padStart(2, "0")}
                    <ArrowRight className="w-3 h-3" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {errors?.duplicate_groups && errors.duplicate_groups.length > 0 && (
            <div>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-1.5">
                Duplicate melt numbers found:
              </p>
              <div className="space-y-1.5">
                {errors.duplicate_groups.map((g) => (
                  <div
                    key={g.melt_number}
                    className="flex items-center justify-between gap-2 text-sm rounded-lg border border-amber-200 dark:border-amber-700/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2"
                  >
                    <span className="font-mono text-amber-700 dark:text-amber-400 truncate">
                      {g.melt_number}
                    </span>
                    <div className="flex gap-1 shrink-0">
                      {g.s_nos.map((sNo) => (
                        <button
                          key={sNo}
                          type="button"
                          onClick={() => onJumpToRow(sNo)}
                          className="text-xs font-mono rounded-full px-2 py-0.5 bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/60"
                        >
                          Row {String(sNo).padStart(2, "0")}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!errors?.incomplete_rows?.length && !errors?.duplicate_groups?.length && errors?.message && (
            <p className="text-sm text-slate-600 dark:text-slate-300">{errors.message}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button onClick={onRetry} disabled={submitting} className="bg-orange-500 hover:bg-orange-600 text-white">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Re-check
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
