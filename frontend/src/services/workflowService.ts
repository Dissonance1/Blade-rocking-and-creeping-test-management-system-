import api from "./api";
import type { DashboardStats, WorkflowHistoryResponse } from "@/types";

export const workflowService = {
  getDashboardStats: async (): Promise<DashboardStats> => {
    const { data } = await api.get<DashboardStats>("/workflows/dashboard/stats");
    return data;
  },

  // Backend URL: /workflows/history/{blade_id}
  getHistory: async (bladeId: string): Promise<WorkflowHistoryResponse> => {
    const { data } = await api.get<WorkflowHistoryResponse>(
      `/workflows/history/${bladeId}`
    );
    return data;
  },

  getDailyThroughput: async (days = 7): Promise<
    { date: string; created: number; completed: number; rejected: number }[]
  > => {
    const { data } = await api.get(`/workflows/dashboard/throughput?days=${days}`);
    return data as { date: string; created: number; completed: number; rejected: number }[];
  },

  /** Alias kept for pages that call getTransitions */
  getTransitions: async (bladeId: string): Promise<WorkflowHistoryResponse> => {
    const { data } = await api.get<WorkflowHistoryResponse>(`/workflows/history/${bladeId}`);
    return data;
  },

  getTimeline: async (bladeId: string): Promise<WorkflowHistoryResponse> => {
    const { data } = await api.get<WorkflowHistoryResponse>(
      `/workflows/timeline/${bladeId}`
    );
    return data;
  },
};
