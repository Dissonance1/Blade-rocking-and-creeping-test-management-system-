import api from "./api";
import type { Notification, PaginatedResponse, NotificationQueryParams } from "@/types";

export const notificationService = {
  list: async (params: NotificationQueryParams = {}): Promise<Notification[]> => {
    const { data } = await api.get<PaginatedResponse<Notification>>("/notifications/", { params });
    return data.items ?? [];
  },

  /** Same endpoint, but returns `total` too so callers can drive a "Load more". */
  listPaginated: async (params: NotificationQueryParams = {}): Promise<PaginatedResponse<Notification>> => {
    const { data } = await api.get<PaginatedResponse<Notification>>("/notifications/", { params });
    return data;
  },

  // Backend uses POST, not PATCH
  markRead: async (id: string): Promise<void> => {
    await api.post(`/notifications/${id}/read`);
  },

  // Backend uses POST, not PATCH
  markAllRead: async (): Promise<void> => {
    await api.post("/notifications/read-all");
  },

  getUnreadCount: async (): Promise<number> => {
    const { data } = await api.get<{ unread_count: number }>("/notifications/unread-count");
    return data.unread_count ?? 0;
  },
};
