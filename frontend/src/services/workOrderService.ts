import api from "./api";

export type BladeType = "LPTR" | "HPTR";

export interface WorkOrderCreatePayload {
  work_order_number: string;
  shop_order_number: string;
  part_number: string;
  blade_type: BladeType;
  engine_number?: string | null;
  engine_hours: string;
  component_hours?: string | null;
}

export interface WorkOrderRowUpdatePayload {
  melt_number?: string | null;
  ocr_melt_number?: string | null;
  ocr_mismatch_flag?: boolean | null;
  ocr_mismatch_notes?: string | null;
  raw_weight?: number | null;
}

export interface WorkOrderRow {
  s_no: number;
  blade_id: string;
  melt_number: string | null;
  ocr_melt_number: string | null;
  ocr_mismatch_flag: boolean;
  raw_weight: number | null;
  weight_grams: number | null;
  static_moment_gcm: number | null;
  is_complete: boolean;
}

export interface WorkOrderDetail {
  work_order_number: string;
  shop_order_number: string;
  part_number: string;
  blade_type: BladeType;
  engine_number: string | null;
  engine_hours: string;
  component_hours: string | null;
  is_entry_complete: boolean;
  entry_completed_at: string | null;
  rows: WorkOrderRow[];
  first_incomplete_s_no: number | null;
}

export interface WorkOrderCompleteResult {
  work_order_number: string;
  status: string;
  blade_ids: string[];
  completed_at: string;
}

export interface WorkOrderCompleteValidationError {
  message: string;
  incomplete_rows?: number[];
  duplicate_groups?: { melt_number: string; s_nos: number[] }[];
}

export const workOrderService = {
  create: async (payload: WorkOrderCreatePayload): Promise<WorkOrderDetail> => {
    const { data } = await api.post<WorkOrderDetail>("/work-orders/", payload);
    return data;
  },

  /** Returns null if the work order doesn't exist yet (404) — used to decide new vs resume. */
  getEntry: async (workOrderNumber: string): Promise<WorkOrderDetail | null> => {
    try {
      const { data } = await api.get<WorkOrderDetail>(
        `/work-orders/${encodeURIComponent(workOrderNumber)}/entry`
      );
      return data;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) return null;
      throw err;
    }
  },

  saveRow: async (
    workOrderNumber: string,
    sNo: number,
    payload: WorkOrderRowUpdatePayload
  ): Promise<WorkOrderRow> => {
    const { data } = await api.put<WorkOrderRow>(
      `/work-orders/${encodeURIComponent(workOrderNumber)}/rows/${sNo}`,
      payload
    );
    return data;
  },

  complete: async (workOrderNumber: string): Promise<WorkOrderCompleteResult> => {
    const { data } = await api.post<WorkOrderCompleteResult>(
      `/work-orders/${encodeURIComponent(workOrderNumber)}/complete`
    );
    return data;
  },
};
