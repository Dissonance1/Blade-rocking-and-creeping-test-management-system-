import api from "./api";
import type { AuthTokens, LoginCredentials, User, UserRole } from "@/types";

/** Raw shape returned by the backend /auth/me endpoint (roles are objects) */
interface BackendUser {
  id: string;
  email: string;
  username: string;
  full_name: string;
  roles: Array<{ id: string; name: string; description?: string | null }>;
  station_id?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  last_login?: string | null;
  created_at: string;
  updated_at: string;
}

/** Normalise backend user shape → frontend User (roles as string array) */
function normaliseUser(raw: BackendUser): User {
  return {
    ...raw,
    roles: raw.roles.map((r) => r.name as UserRole),
  };
}

export const authService = {
  /**
   * Login with email + password (JSON body).
   * Backend returns { access_token, refresh_token, token_type }.
   * Calls /auth/me to get the full user profile.
   */
  login: async (credentials: LoginCredentials): Promise<{ user: User; tokens: AuthTokens }> => {
    const { data } = await api.post<AuthTokens>("/auth/login", {
      email: credentials.email,
      password: credentials.password,
    });

    const tokens: AuthTokens = {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      token_type: data.token_type,
    };

    const { data: rawUser } = await api.get<BackendUser>("/auth/me", {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });

    return { user: normaliseUser(rawUser), tokens };
  },

  changePassword: async (old_password: string, new_password: string): Promise<void> => {
    await api.post("/auth/me/change-password", {
      current_password: old_password,
      new_password,
      confirm_new_password: new_password,
    });
  },
};
