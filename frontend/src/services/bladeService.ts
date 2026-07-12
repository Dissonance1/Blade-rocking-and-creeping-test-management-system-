import api from "./api";
import type {
  Blade,
  BladeListItem,
  BladeCreateRequest,
  BladeUpdateRequest,
  BladeActionRequest,
  BladeRejectRequest,
  Measurement,
  MeasurementCreate,
  PaginatedResponse,
  BladeSearchParams,
  RejectionReason,
} from "@/types";

export interface Attachment {
  id: string;
  blade_id: string;
  filename: string;
  original_filename: string;
  file_path: string;
  file_size_bytes: number;
  mime_type: string;
  attachment_type: "IMAGE" | "DOCUMENT" | "OCR_SCAN";
  uploaded_by_id: string;
  uploaded_at: string;
}

export const bladeService = {
  // ── Blade CRUD ──────────────────────────────────────────────────────────────
  list: async (params: BladeSearchParams = {}): Promise<PaginatedResponse<BladeListItem>> => {
    const { statuses, ...rest } = params;
    const queryParams = {
      ...rest,
      ...(statuses && statuses.length > 0 ? { statuses: statuses.join(",") } : {}),
    };
    const { data } = await api.get<PaginatedResponse<BladeListItem>>("/blades/", { params: queryParams });
    return data;
  },

  get: async (id: string): Promise<Blade> => {
    const { data } = await api.get<Blade>(`/blades/${id}`);
    return data;
  },

  create: async (payload: BladeCreateRequest): Promise<Blade> => {
    const { data } = await api.post<Blade>("/blades/", payload);
    return data;
  },

  update: async (id: string, payload: BladeUpdateRequest): Promise<Blade> => {
    const { data } = await api.put<Blade>(`/blades/${id}`, payload);
    return data;
  },

  deleteBlade: async (id: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.delete(`/blades/${id}`);
    return data;
  },

  setRockingCreep: async (
    bladeId: string,
    payload: { rocking_value?: number | null; creep_value?: number | null }
  ): Promise<Measurement> => {
    const { data } = await api.patch<Measurement>(`/blades/${bladeId}/rocking-creep`, payload);
    return data;
  },

  batchLookup: async (batchNumber: string): Promise<{ found: boolean; work_order_number: string | null; part_number: string | null; engine_number: string | null; nomenclature: string | null }> => {
    const { data } = await api.get("/blades/batch-lookup", { params: { batch_number: batchNumber } });
    return data;
  },

  nextSerialNumber: async (batchNumber: string, bladeType: "LPTR" | "HPTR"): Promise<string> => {
    const { data } = await api.get<{ next_serial_number: string }>("/blades/next-serial-number", {
      params: { batch_number: batchNumber, blade_type: bladeType },
    });
    return data.next_serial_number;
  },

  saveBatchGroup: async (payload: { batch_number: string; work_order_number: string; part_number: string; engine_number?: string; nomenclature?: string }): Promise<void> => {
    await api.post("/blades/batch-groups", payload);
  },

  /**
   * Serial numbers are unique per (batch_number, blade_type) — not globally —
   * since each batch numbers its LPTR and HPTR blades 1..90 independently.
   */
  checkSerialUnique: async (
    serial: string,
    batchNumber: string,
    bladeType: "LPTR" | "HPTR"
  ): Promise<boolean> => {
    try {
      const { data } = await api.get<{ exists: boolean }>("/blades/serial-exists", {
        params: { batch_number: batchNumber, blade_type: bladeType, serial_number: serial },
      });
      return !data.exists;
    } catch {
      return true;
    }
  },

  // ── Aliases for backward compatibility with existing page code ───────────────
  recordMeasurements: async (bladeId: string, payload: MeasurementCreate): Promise<Measurement> => {
    const { data } = await api.post<Measurement>(`/blades/${bladeId}/measurements`, payload);
    return data;
  },

  transition: async (bladeId: string, payload: { to_status: string; remarks?: string }): Promise<Blade> => {
    // Map to_status to the appropriate action endpoint
    const actionMap: Record<string, string> = {
      SENT_TO_ASSEMBLY: "send-to-assembly",
      RETURNED_TO_OH: "return-to-oh",
      COMPLETED: "complete",
      REJECTED: "reject",
      REOPENED: "reopen",
      ON_HOLD: "hold",
    };
    const action = actionMap[payload.to_status] ?? "hold";
    const { data } = await api.post<Blade>(`/blades/${bladeId}/${action}`, { remarks: payload.remarks });
    return data;
  },

  // ── Workflow actions ─────────────────────────────────────────────────────────
  sendToAssembly: async (id: string, payload?: BladeActionRequest): Promise<Blade> => {
    const { data } = await api.post<Blade>(`/blades/${id}/send-to-assembly`, payload ?? {});
    return data;
  },

  returnToOH: async (id: string, payload?: BladeActionRequest): Promise<Blade> => {
    const { data } = await api.post<Blade>(`/blades/${id}/return-to-oh`, payload ?? {});
    return data;
  },

  complete: async (id: string, payload?: BladeActionRequest): Promise<Blade> => {
    const { data } = await api.post<Blade>(`/blades/${id}/complete`, payload ?? {});
    return data;
  },

  reject: async (id: string, payload: BladeRejectRequest): Promise<Blade> => {
    const { data } = await api.post<Blade>(`/blades/${id}/reject`, payload);
    return data;
  },

  reopen: async (id: string, payload?: BladeActionRequest): Promise<Blade> => {
    const { data } = await api.post<Blade>(`/blades/${id}/reopen`, payload ?? {});
    return data;
  },

  hold: async (id: string, payload?: BladeActionRequest): Promise<Blade> => {
    const { data } = await api.post<Blade>(`/blades/${id}/hold`, payload ?? {});
    return data;
  },

  // ── Measurements ─────────────────────────────────────────────────────────────
  getMeasurements: async (bladeId: string): Promise<Measurement[]> => {
    const { data } = await api.get<Measurement[]>(`/blades/${bladeId}/measurements`);
    const items = Array.isArray(data) ? data : (data as any).items ?? [];
    return items;
  },

  addMeasurement: async (bladeId: string, payload: MeasurementCreate): Promise<Measurement> => {
    const { data } = await api.post<Measurement>(`/blades/${bladeId}/measurements`, payload);
    return data;
  },

  // ── Attachments ──────────────────────────────────────────────────────────────
  getAttachments: async (bladeId: string): Promise<Attachment[]> => {
    const { data } = await api.get<any>(`/blades/${bladeId}/attachments`);
    return Array.isArray(data) ? data : data?.items ?? [];
  },

  deleteAttachment: async (bladeId: string, attachmentId: string): Promise<void> => {
    await api.delete(`/blades/${bladeId}/attachments/${attachmentId}`);
  },

  uploadAttachment: async (bladeId: string, file: File): Promise<Attachment> => {
    const fd = new FormData();
    fd.append("file", file);
    // Clear the instance-default Content-Type so Axios auto-sets
    // "multipart/form-data; boundary=..." based on the FormData body.
    const { data } = await api.post<Attachment>(`/blades/${bladeId}/attachments`, fd, {
      headers: { "Content-Type": undefined },
    });
    return data;
  },

  attachOcrScan: async (bladeId: string, scanId: string, label: "serial_number" | "melt_number"): Promise<void> => {
    await api.post(`/blades/${bladeId}/attach-ocr-scan`, { scan_id: scanId, label });
  },
};

// ── Rejection reasons ─────────────────────────────────────────────────────────
export const rejectionReasonService = {
  list: async (): Promise<RejectionReason[]> => {
    // Rejection reasons are returned as part of master data from stations
    // For now fetch all active ones via a generic endpoint
    const { data } = await api.get<RejectionReason[]>("/blades/rejection-reasons/");
    return data;
  },
};
