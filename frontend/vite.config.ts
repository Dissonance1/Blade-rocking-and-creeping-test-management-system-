import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react()],

    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },

    server: {
      port: 3000,
      strictPort: true,
      proxy: {
        "/api": {
          target: env.VITE_DEV_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
          secure: false,
          rewrite: (path) => path.replace(/^\/api/, "/api"),
        },
        "/ws": {
          target: env.VITE_DEV_PROXY_WS_TARGET || "ws://localhost:8000",
          ws: true,
          changeOrigin: true,
          secure: false,
        },
      },
    },

    build: {
      sourcemap: true,
      target: "esnext",
      minify: "esbuild",
      rollupOptions: {
        output: {
          manualChunks: {
            // React core
            "vendor-react": ["react", "react-dom", "react-router-dom"],
            // UI libraries
            "vendor-ui": [
              "lucide-react",
              "sonner",
              "class-variance-authority",
              "clsx",
              "tailwind-merge",
            ],
            // Radix UI primitives
            "vendor-radix": [
              "@radix-ui/react-dialog",
              "@radix-ui/react-dropdown-menu",
              "@radix-ui/react-select",
              "@radix-ui/react-tabs",
              "@radix-ui/react-avatar",
              "@radix-ui/react-tooltip",
              "@radix-ui/react-popover",
              "@radix-ui/react-scroll-area",
            ],
            // Data / state
            "vendor-data": [
              "@tanstack/react-query",
              "@tanstack/react-table",
              "zustand",
              "axios",
            ],
            // Charts
            "vendor-charts": ["recharts"],
            // Forms
            "vendor-forms": [
              "react-hook-form",
              "@hookform/resolvers",
              "zod",
            ],
            // Utilities
            "vendor-utils": ["date-fns"],
          },
        },
      },
      chunkSizeWarningLimit: 1000,
    },

    preview: {
      port: 4173,
    },
  };
});
