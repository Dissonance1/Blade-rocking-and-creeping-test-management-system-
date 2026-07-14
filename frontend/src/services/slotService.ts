import api from "./api";
import type { SlotAllocation, BalancingUpdate, PaginatedResponse } from "@/types";

export const slotService = {
  list: async (params?: { skip?: number; limit?: number; work_order_number?: string }): Promise<SlotAllocation[]> => {
    const { data } = await api.get<PaginatedResponse<SlotAllocation>>("/slots/", { params });
    // Backend returns paginated; extract items array
    return Array.isArray(data) ? data : (data as PaginatedResponse<SlotAllocation>).items ?? [];
  },

  update: async (id: string, payload: BalancingUpdate): Promise<SlotAllocation> => {
    const { data } = await api.put<SlotAllocation>(`/slots/${id}/balancing`, payload);
    return data;
  },
};
