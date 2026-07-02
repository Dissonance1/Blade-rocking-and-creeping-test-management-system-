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
  scanSerial: async (file: File): Promise<OcrScanResult> => {
    const form = new FormData();
    form.append("image", file);
    const { data } = await api.post<OcrScanResult>("/ocr/scan/blade-serial", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },

  scanMelt: async (file: File): Promise<OcrScanResult> => {
    const form = new FormData();
    form.append("image", file);
    const { data } = await api.post<OcrScanResult>("/ocr/scan/melt-number", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },
};
