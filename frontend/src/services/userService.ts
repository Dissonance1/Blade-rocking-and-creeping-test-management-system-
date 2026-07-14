import api from "./api";
import type { User, UserRole, PaginatedResponse } from "@/types";

export interface CreateUserPayload {
  full_name: string;
  email: string;
  username: string;
  password: string;
  roles?: string[];
  station_id?: string;
}

export interface UpdateUserPayload {
  full_name?: string;
  is_active?: boolean;
  station_id?: string;
}

/** Backend list response uses `role_names`; normalise to `roles` for the UI */
interface BackendUserListItem {
  id: string;
  email: string;
  username: string;
  full_name: string;
  is_active: boolean;
  station_id?: string | null;
  role_names?: UserRole[];
  roles?: UserRole[];
  created_at: string;
  last_login?: string | null;
  is_superuser?: boolean;
  updated_at?: string;
}

function normaliseUser(u: BackendUserListItem): User {
  return {
    ...u,
    full_name: u.full_name ?? "",
    is_superuser: u.is_superuser ?? false,
    updated_at: u.updated_at ?? u.created_at,
    // Prefer role_names (list endpoint) or roles (detail endpoint)
    roles: (u.role_names ?? u.roles ?? []) as UserRole[],
  };
}

export const userService = {
  list: async (params?: { skip?: number; limit?: number }): Promise<PaginatedResponse<User>> => {
    const { data } = await api.get<PaginatedResponse<BackendUserListItem>>("/users/", { params });
    return {
      ...data,
      items: data.items.map(normaliseUser),
    };
  },

  create: async (payload: CreateUserPayload): Promise<User> => {
    const { data } = await api.post<BackendUserListItem>("/users/", payload);
    const user = normaliseUser(data);
    // Assign initial roles if specified (body must be a raw JSON array)
    if (payload.roles?.length) {
      try {
        await api.post(`/users/${user.id}/roles`, payload.roles);
      } catch {
        // Role assignment failure is non-fatal; user was created successfully
      }
    }
    return user;
  },

  update: async (id: string, payload: UpdateUserPayload): Promise<User> => {
    const { data } = await api.put<BackendUserListItem>(`/users/${id}`, payload);
    return normaliseUser(data);
  },

  // Backend expects a raw JSON array: ["OH_OPERATOR"]
  assignRole: async (userId: string, roleName: UserRole): Promise<void> => {
    await api.post(`/users/${userId}/roles`, [roleName]);
  },

  // DELETE /users/{id}/roles/{role_name} — role_name in path
  removeRole: async (userId: string, roleName: UserRole): Promise<void> => {
    await api.delete(`/users/${userId}/roles/${roleName}`);
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/users/${id}`);
  },
};
