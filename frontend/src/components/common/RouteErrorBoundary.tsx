import { useEffect } from "react";
import { isRouteErrorResponse, useNavigate, useRouteError } from "react-router-dom";

/**
 * Replaces React Router's default "Unexpected Application Error!" crash page.
 * Vite HMR occasionally throws a stale-module error after a file rename/move —
 * that's transient, so we auto-reload once instead of showing a dead end.
 */
export default function RouteErrorBoundary() {
  const error = useRouteError();
  const navigate = useNavigate();

  const message = isRouteErrorResponse(error)
    ? error.statusText || `Error ${error.status}`
    : error instanceof Error
      ? error.message
      : "Something went wrong.";

  const isStaleModule = /is not defined|Failed to fetch dynamically imported module|dynamically imported module/i.test(
    message
  );

  const hasAttemptedReload = sessionStorage.getItem("route-error-reload-attempted") === "1";

  useEffect(() => {
    if (isStaleModule) {
      if (!hasAttemptedReload) {
        sessionStorage.setItem("route-error-reload-attempted", "1");
        window.location.reload();
      }
    }
  }, [isStaleModule, hasAttemptedReload]);

  if (isStaleModule && !hasAttemptedReload) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-4">
          <div className="h-10 w-10 rounded-full border-4 border-slate-200 border-t-orange-500 animate-spin" />
          <p className="text-sm text-slate-500">Loading…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-white p-6">
      <div className="max-w-md w-full text-center">
        <div className="h-10 w-10 mx-auto mb-4 rounded-full border-4 border-slate-200 border-t-red-500 animate-spin" />
        <h1 className="text-lg font-bold text-slate-900 mb-1">Something went wrong</h1>
        <p className="text-sm text-slate-500 mb-6 break-words">{message}</p>
        <button
          onClick={() => navigate(0)}
          className="inline-flex items-center justify-center min-h-11 px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold transition-colors"
        >
          Reload
        </button>
      </div>
    </div>
  );
}
