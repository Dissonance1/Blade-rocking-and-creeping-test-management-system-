import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { Toaster } from "sonner";

import App from "@/App";
import ErrorBoundary from "@/components/common/ErrorBoundary";
import "@/index.css";

/* ─── React Query client ─────────────────────────────────────────────────── */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,           // 30 s — matches the poll interval
      gcTime: 5 * 60_000,          // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
      refetchInterval: 30_000,     // background poll every 30 s
    },
    mutations: {
      retry: 0,
    },
  },
});

/* ─── Root render ────────────────────────────────────────────────────────── */
const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Root element #root not found in index.html");

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />

        {/* Toast notifications */}
        <Toaster
          position="top-right"
          richColors
          closeButton
          duration={4000}
          toastOptions={{
            classNames: {
              toast: "font-sans text-sm",
            },
          }}
        />

        {/* Dev tools (stripped in production by tree-shaking) */}
        {import.meta.env.DEV && (
          <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-right" />
        )}
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
