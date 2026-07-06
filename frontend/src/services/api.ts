/**
 * Axios instance — shared HTTP client for all API services.
 *
 * Features:
 *  - JWT attached on every request via request interceptor
 *  - Automatic silent token refresh on 401 (single retry per request)
 *  - Redirect to /login when refresh itself fails
 *  - Typed error-extraction helper: extractApiError(error: unknown) -> string
 *
 * NOTE: "Cannot find module 'axios'" and "Property 'env' does not exist on
 * ImportMeta" errors disappear after running `npm install` and having the
 * generated `vite-env.d.ts` picked up by the TS server.  They are not real
 * source errors.
 */

import axios from "axios";
import type {
  AxiosInstance,
  AxiosResponse,
  AxiosError,
  InternalAxiosRequestConfig,
} from "axios";
import type { ApiError, ApiValidationError } from "@/types";

// In production (behind NGINX), VITE_API_BASE_URL is empty → same-origin proxying.
// In local dev, set VITE_API_BASE_URL=http://localhost:8000 in frontend/.env
export const BASE_URL: string =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (import.meta as any).env?.VITE_API_BASE_URL ?? "";

// ─── Axios instance ───────────────────────────────────────────────────────────

const api: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

// ─── Lazy store accessor ──────────────────────────────────────────────────────
//
// authStore → api.ts is a circular dependency at module-load time.
// We break it by caching the store module lazily on first use.

type AuthStoreModule = typeof import("@/store/authStore");
let _authStoreMod: AuthStoreModule | null = null;

async function getAuthStore(): Promise<AuthStoreModule> {
  if (!_authStoreMod) {
    _authStoreMod = await import("@/store/authStore");
  }
  return _authStoreMod;
}

function getAuthStoreSync(): AuthStoreModule | null {
  return _authStoreMod;
}

// Eagerly warm the cache on module load so the request interceptor has it.
void import("@/store/authStore").then((mod) => {
  _authStoreMod = mod;
});

// ─── Request interceptor: attach access token ────────────────────────────────

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig): InternalAxiosRequestConfig => {
    const store = getAuthStoreSync();
    const accessToken = store?.useAuthStore.getState().accessToken ?? null;
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    return config;
  },
  (error: unknown) => Promise.reject(error),
);

// ─── Parallel-refresh queue ───────────────────────────────────────────────────

let isRefreshing = false;
let refreshQueue: Array<{
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}> = [];

function processQueue(error: unknown, token: string | null = null): void {
  for (const p of refreshQueue) {
    if (error) p.reject(error);
    else if (token) p.resolve(token);
  }
  refreshQueue = [];
}

// ─── Response interceptor: silent token refresh on 401 ───────────────────────

api.interceptors.response.use(
  (response: AxiosResponse): AxiosResponse => response,
  async (rawError: unknown): Promise<AxiosResponse> => {
    // Narrow to AxiosError; propagate anything else immediately.
    if (!axios.isAxiosError(rawError)) return Promise.reject(rawError);

    const error = rawError as AxiosError;
    const originalRequest = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined;

    // Propagate if: not 401, no config, or already retried once.
    if (
      error.response?.status !== 401 ||
      !originalRequest ||
      originalRequest._retry
    ) {
      return Promise.reject(error);
    }

    // A failed login attempt is not an expired session — just propagate the
    // error so the login form can show it. Redirecting here would wipe the
    // page (and the error message) before the form ever sees it.
    const url = originalRequest.url ?? "";
    if (url.includes("/auth/login")) {
      return Promise.reject(error);
    }

    // Don't refresh for the refresh endpoint itself — avoids infinite loops.
    if (url.includes("/auth/refresh")) {
      await doLogout();
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    // Queue if another refresh is already in-flight.
    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        refreshQueue.push({ resolve, reject });
      }).then((newToken) => {
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      });
    }

    isRefreshing = true;

    try {
      const { useAuthStore } = await getAuthStore();
      const refreshToken = useAuthStore.getState().refreshToken;

      if (!refreshToken) {
        await doLogout();
        return Promise.reject(error);
      }

      const { data } = await axios.post<{ access_token: string }>(
        `${BASE_URL}/api/v1/auth/refresh`,
        { refresh_token: refreshToken },
      );

      const newAccessToken = data.access_token;
      useAuthStore.getState().setTokens(newAccessToken, refreshToken);

      processQueue(null, newAccessToken);
      originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
      return api(originalRequest);
    } catch (refreshError) {
      processQueue(refreshError, null);
      await doLogout();
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  },
);

// ─── Internal helper ──────────────────────────────────────────────────────────

async function doLogout(): Promise<void> {
  const store = await getAuthStore();
  store.useAuthStore.getState().logout();
  window.location.replace("/login");
}

// ─── Public helper ────────────────────────────────────────────────────────────

/**
 * Extracts a human-readable message from any thrown value.
 * Handles FastAPI `{ detail: string }` and `{ detail: ValidationError[] }`.
 */
export function extractApiError(error: unknown): string {
  if (!axios.isAxiosError(error)) {
    if (error instanceof Error) return error.message;
    return "An unexpected error occurred.";
  }

  // After isAxiosError guard, `error` is AxiosError — data may be anything.
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const body = error.response?.data as (ApiError & { message?: string; errors?: { field?: string; message?: string }[] }) | null | undefined;

  // Our backend sends { success, message, errors } — check message first
  if (body?.message && typeof body.message === "string") {
    // If there are field-level errors, append them for context
    const fieldErrors = (body.errors ?? [])
      .filter((e) => e.message)
      .map((e) => (e.field ? `${e.field}: ${e.message}` : e.message!))
      .join("; ");
    return fieldErrors ? `${body.message} (${fieldErrors})` : body.message;
  }

  // Fallback: standard FastAPI { detail } format
  if (body?.detail) {
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return (body.detail as ApiValidationError[])
        .map((e) => `${e.loc.join(" → ")}: ${e.msg}`)
        .join("; ");
    }
  }

  return error.message || "Request failed.";
}

export default api;
