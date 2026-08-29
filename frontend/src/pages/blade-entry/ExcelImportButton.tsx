import { useRef, useState } from "react";
import { FileSpreadsheet, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { extractApiError } from "@/services/api";
import type { WorkOrderBulkImportResult } from "@/services/workOrderService";
import ExcelImportResultDialog from "./ExcelImportResultDialog";

/**
 * Shared "Upload Excel" trigger — hidden file input + button + result
 * dialog. Callers own what the import actually does (create-then-import on
 * the Start screen, straight import on the grid); this just owns the file
 * picker, in-flight state, and the result/error presentation.
 */
export default function ExcelImportButton({
  label = "Upload Excel",
  confirmMessage,
  onImport,
  onDialogClosed,
  disabled,
}: {
  label?: string;
  /** If set, shown via window.confirm before the file is uploaded. */
  confirmMessage?: string;
  onImport: (file: File) => Promise<WorkOrderBulkImportResult>;
  /** Fires after the result/error dialog is dismissed (success or failure). */
  onDialogClosed?: () => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WorkOrderBulkImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFile = async (file: File) => {
    if (confirmMessage && !window.confirm(confirmMessage)) return;
    setBusy(true);
    setError(null);
    try {
      const res = await onImport(file);
      setResult(res);
    } catch (err) {
      setError(extractApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx,.xls"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void handleFile(file);
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || busy}
        onClick={() => inputRef.current?.click()}
        className="gap-1.5"
      >
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileSpreadsheet className="w-3.5 h-3.5" />}
        {label}
      </Button>

      {error && (
        <ExcelImportResultDialog
          open
          result={{ imported_count: 0, skipped_count: 0, errors: [{ s_no: null, message: error }], rows: [] }}
          onClose={() => {
            setError(null);
            onDialogClosed?.();
          }}
        />
      )}
      <ExcelImportResultDialog
        open={!!result}
        result={result}
        onClose={() => {
          setResult(null);
          onDialogClosed?.();
        }}
      />
    </>
  );
}
