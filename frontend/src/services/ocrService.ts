import api from "./api";
import { shouldUseLocalOcr, scanViaLocalOcr } from "./localOcr";
import { getHardwareStation } from "@/utils/hardwareStation";

export interface OcrScanResult {
  value: string;
  confidence: number;
  raw_text: string;
  provider: string;
  processing_time_ms?: number | null;
  error?: string | null;
  scan_id: string;
  /**
   * True when this scan came from a local OCR companion service (see
   * localOcr.ts / scripts/hptr_ocr_service.py) whose image hasn't reached
   * the OH backend yet — it uploads in the background shortly after. Passed
   * through to attachScan so the OH backend doesn't 404 on a scan_id it
   * minted before the image existed.
   */
  image_pending?: boolean;
  /**
   * Which physical station produced this scan (e.g. "1", "2") — either this
   * station's own picker value (central path) or the local OCR companion's
   * own --station value (remote path, more authoritative). Passed through to
   * attachScan so it lands on the Attachment record for provenance.
   */
  hardware_station?: string | null;
}

export const ocrService = {
  scanMelt: async (file: File): Promise<OcrScanResult> => {
    // Prefer this station's own OCR companion service when one answers
    // locally (see localOcr.ts) — keeps this station's OCR load off the OH
    // backend. Falls back to the central endpoint below on any failure (no
    // local service on this machine, unreachable, still warming up, etc.)
    // so a scan never fails outright just because the local service had a
    // bad moment.
    if (await shouldUseLocalOcr()) {
      try {
        return await scanViaLocalOcr(file, "melt-number");
      } catch {
        // fall through to the central endpoint
      }
    }
    const form = new FormData();
    form.append("image", file);
    form.append("hardware_station", getHardwareStation());
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
    confidence?: number | null,
    imagePending?: boolean,
    hardwareStation?: string | null
  ): Promise<void> => {
    await api.post(`/blades/${bladeId}/attach-ocr-scan`, {
      scan_id: scanId,
      label,
      detected_text: detectedText,
      confidence,
      image_pending: imagePending ?? false,
      hardware_station: hardwareStation ?? null,
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
