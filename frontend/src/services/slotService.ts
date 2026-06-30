import api from "./api";
import type { SlotAllocation, SlotAssignRequest, BalancingUpdate, PaginatedResponse } from "@/types";

export const slotService = {
  list: async (params?: { skip?: number; limit?: number; batch_number?: string }): Promise<SlotAllocation[]> => {
    const { data } = await api.get<PaginatedResponse<SlotAllocation>>("/slots/", { params });
    // Backend returns paginated; extract items array
    return Array.isArray(data) ? data : (data as PaginatedResponse<SlotAllocation>).items ?? [];
  },

  listPaginated: async (params?: { skip?: number; limit?: number }): Promise<PaginatedResponse<SlotAllocation>> => {
    const { data } = await api.get<PaginatedResponse<SlotAllocation>>("/slots/", { params });
    return data;
  },

  getByBlade: async (bladeId: string): Promise<SlotAllocation | null> => {
    const { data } = await api.get<SlotAllocation | null>(`/slots/blade/${bladeId}`);
    return data;
  },

  create: async (payload: SlotAssignRequest): Promise<SlotAllocation> => {
    const { data } = await api.post<SlotAllocation>("/slots/assign", payload);
    return data;
  },

  reassign: async (payload: { blade_id: string; new_slot_number: string; reason: string }): Promise<SlotAllocation> => {
    const { data } = await api.post<SlotAllocation>("/slots/reassign", payload);
    return data;
  },

  update: async (id: string, payload: BalancingUpdate): Promise<SlotAllocation> => {
    const { data } = await api.put<SlotAllocation>(`/slots/${id}/balancing`, payload);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/slots/${id}`);
  },
};
