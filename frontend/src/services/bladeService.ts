import api from "./api";
import type {
  Blade,
  BladeListItem,
  Measurement,
  PaginatedResponse,
  BladeSearchParams,
} from "@/types";

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

  transition: async (bladeId: string, payload: { to_status: string; remarks?: string }): Promise<Blade> => {
    // Map to_status to the appropriate action endpoint
    const actionMap: Record<string, string> = {
      SENT_TO_ASSEMBLY: "send-to-assembly",
      RETURNED_TO_OH: "return-to-oh",
      COMPLETED: "complete",
      REJECTED: "reject",
      REOPENED: "reopen",
    };
    const action = actionMap[payload.to_status];
    if (!action) throw new Error(`No transition action mapped for status ${payload.to_status}`);
    const { data } = await api.post<Blade>(`/blades/${bladeId}/${action}`, { remarks: payload.remarks });
    return data;
  },
};
