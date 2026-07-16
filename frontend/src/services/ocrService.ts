import api from "./api";

export interface OcrScanResult {
  value: string;
  confidence: number;
  raw_text: string;
  provider: string;
  processing_time_ms?: number | null;
  error?: string | null;
  scan_id: string;
}

export const ocrService = {
  scanMelt: async (file: File): Promise<OcrScanResult> => {
    const form = new FormData();
    form.append("image", file);
    const { data } = await api.post<OcrScanResult>("/ocr/scan/melt-number", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  /**
   * Link a previously saved OCR scan image to a blade as an OCR_SCAN
   * attachment, preserving the OCR's raw detection + confidence alongside
   * it — this is what makes the scan usable later as a training/eval
   * dataset entry (image + detected_text, paired at export time with the
   * blade's ground-truth field).
   */
  attachScan: async (
    bladeId: string,
    scanId: string,
    label: string,
    detectedText?: string | null,
    confidence?: number | null
  ): Promise<void> => {
    await api.post(`/blades/${bladeId}/attach-ocr-scan`, {
      scan_id: scanId,
      label,
      detected_text: detectedText,
      confidence,
    });
  },

  /**
   * Download the OCR training dataset ZIP (images + manifest.jsonl pairing
   * detected_text/confidence with the operator-confirmed ground truth).
   * Set mismatchesOnly to pull just the cases where the model got it wrong.
   */
  downloadTrainingDataset: async (
    fieldName: string,
    mismatchesOnly: boolean
  ): Promise<void> => {
    const { data, headers } = await api.get("/ocr/training-dataset", {
      params: { field_name: fieldName, mismatches_only: mismatchesOnly },
      responseType: "blob",
    });
    const contentDisp = (headers["content-disposition"] as string) ?? "";
    const nameMatch = contentDisp.match(/filename="?([^";\n]+)"?/);
    const downloadName = nameMatch?.[1] ?? `ocr_training_dataset_${fieldName}.zip`;

    const blob = new Blob([data as BlobPart], { type: "application/zip" });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = downloadName;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.URL.revokeObjectURL(url);
  },
};
