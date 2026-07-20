import api from "./api";
import type { Report, ReportType, PaginatedResponse } from "@/types";

export interface GenerateReportPayload {
  name: string;
  report_type: ReportType;
  filter_params?: {
    blade_ids?: string[];
    status?: string[];
    station_id?: string;
    date_from?: string;
    date_to?: string;
    include_rejected?: boolean;
  };
}

export const reportService = {
  list: async (params?: { skip?: number; limit?: number }): Promise<PaginatedResponse<Report>> => {
    const { data } = await api.get<PaginatedResponse<Report>>("/reports/", { params });
    return data;
  },

  generate: async (payload: GenerateReportPayload): Promise<Report> => {
    const { data } = await api.post<Report>("/reports/generate", payload);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/reports/${id}`);
  },

  /** Trigger a browser download for a completed report (uses Authorization header). */
  download: async (id: string, filename?: string): Promise<void> => {
    const { data, headers } = await api.get(`/reports/${id}/download`, {
      responseType: "blob",
    });
    const contentDisp = (headers["content-disposition"] as string) ?? "";
    const nameMatch = contentDisp.match(/filename="?([^";\n]+)"?/);
    const downloadName = nameMatch?.[1] ?? filename ?? `report_${id}`;

    const blob = new Blob([data as BlobPart]);
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = downloadName;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.URL.revokeObjectURL(url);
  },

  /**
   * Batch report export: one row per blade (slot, serial, melt, weight,
   * static moment, rocking, and creep for LPTR work orders) — triggers
   * the browser download directly, no Report DB row created.
   */
  exportBatchReport: async (workOrderNumber: string, fileFormat: "excel" | "pdf"): Promise<void> => {
    const { data } = await api.get(
      "/reports/export/batch",
      { params: { work_order_number: workOrderNumber, format: fileFormat }, responseType: "blob" }
    );
    const mime =
      fileFormat === "pdf"
        ? "application/pdf"
        : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    const ext = fileFormat === "pdf" ? "pdf" : "xlsx";
    const blob = new Blob([data as BlobPart], { type: mime });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `batch_report_${workOrderNumber}.${ext}`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.URL.revokeObjectURL(url);
  },

  /** Excel export of a batch's saved HPTR slot assignments (W1/W2 sheets) — triggers the browser download directly. */
  exportHptrSlots: async (batchNumber: string): Promise<void> => {
    const { data } = await api.post(
      "/reports/export/hptr-slots",
      {},
      { params: { work_order_number: batchNumber }, responseType: "blob" }
    );
    const blob = new Blob([data as BlobPart], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `hptr_slots_${batchNumber}.xlsx`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.URL.revokeObjectURL(url);
  },

  /** Excel export of a batch's saved LPTR two-stage slot assignments (Stage 1/2 + audit sheet) — triggers the browser download directly. */
  exportLptrSlots: async (batchNumber: string): Promise<void> => {
    const { data } = await api.post(
      "/reports/export/lptr-slots",
      {},
      { params: { work_order_number: batchNumber }, responseType: "blob" }
    );
    const blob = new Blob([data as BlobPart], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `lptr_slots_${batchNumber}.xlsx`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.URL.revokeObjectURL(url);
  },
};
