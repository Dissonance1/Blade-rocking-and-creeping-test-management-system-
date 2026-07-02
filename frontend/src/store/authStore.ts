import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User, AuthTokens } from "@/types";

interface AuthState {
  user: User | null;
  tokens: AuthTokens | null;
  // Convenience accessors used by api.ts interceptors
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;

  setAuth: (user: User, tokens: AuthTokens) => void;
  setUser: (user: User) => void;
  setTokens: (accessToken: string, refreshToken: string) => void;
  clearAuth: () => void;
  logout: () => void;
  hasRole: (role: UserRole | UserRole[]) => boolean;
}

type UserRole = User["roles"][number];

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      tokens: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,

      setAuth: (user, tokens) =>
        set({
          user,
          tokens,
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          isAuthenticated: true,
        }),

      setUser: (user) => set({ user }),

      setTokens: (accessToken, refreshToken) =>
        set((state) => ({
          accessToken,
          refreshToken,
          tokens: state.tokens
            ? { ...state.tokens, access_token: accessToken, refresh_token: refreshToken }
            : null,
        })),

      clearAuth: () =>
        set({
          user: null,
          tokens: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
        }),

      logout: () => {
        get().clearAuth();
      },

      hasRole: (role) => {
        const { user } = get();
        if (!user) return false;
        if (Array.isArray(role)) return role.some((r) => user.roles.includes(r));
        return user.roles.includes(role);
      },
    }),
    {
      name: "blade-auth",
      partialize: (state) => ({
        user: state.user,
        tokens: state.tokens,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
