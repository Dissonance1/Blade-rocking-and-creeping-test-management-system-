import { AlertTriangle, CheckCircle2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { WorkOrderBulkImportResult } from "@/services/workOrderService";

export default function ExcelImportResultDialog({
  open,
  result,
  onClose,
}: {
  open: boolean;
  result: WorkOrderBulkImportResult | null;
  onClose: () => void;
}) {
  const hasErrors = !!result?.errors.length;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle
            className={
              hasErrors
                ? "flex items-center gap-2 text-amber-600 dark:text-amber-400"
                : "flex items-center gap-2 text-emerald-600 dark:text-emerald-400"
            }
          >
            {hasErrors ? <AlertTriangle className="w-5 h-5" /> : <CheckCircle2 className="w-5 h-5" />}
            Excel import {hasErrors ? "finished with errors" : "complete"}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {result?.imported_count ?? 0} row(s) imported
            {hasErrors ? `, ${result?.skipped_count} row(s) skipped.` : "."}
          </p>

          {hasErrors && (
            <div className="max-h-72 overflow-y-auto space-y-1.5">
              {result?.errors.map((err, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-2 text-sm rounded-lg border border-amber-200 dark:border-amber-700/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2"
                >
                  {err.s_no != null && (
                    <span className="text-xs font-mono rounded-full px-2 py-0.5 bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 shrink-0">
                      Row {String(err.s_no).padStart(2, "0")}
                    </span>
                  )}
                  <span className="text-amber-700 dark:text-amber-300">{err.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button onClick={onClose} className="bg-orange-500 hover:bg-orange-600 text-white">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
