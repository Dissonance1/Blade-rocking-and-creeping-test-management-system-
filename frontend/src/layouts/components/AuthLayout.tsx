import { Outlet } from "react-router-dom";
import { Wind } from "lucide-react";

const APP_TITLE =
  (import.meta.env.VITE_APP_TITLE as string | undefined) ??
  "Blade Rocking & Creep Test System";

const APP_VERSION =
  (import.meta.env.VITE_APP_VERSION as string | undefined) ?? "1.0.0";

export default function AuthLayout() {
  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-slate-900 via-slate-800 to-orange-950 dark:from-background dark:via-background dark:to-background">
      {/* Subtle grid overlay */}
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.8) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.8) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      {/* Main centered area */}
      <div className="flex-1 flex items-center justify-center px-4 py-12 relative">
        <div className="w-full max-w-md space-y-6">
          {/* Company branding */}
          <div className="text-center space-y-3">
            <div className="inline-flex items-center justify-center h-16 w-16 rounded-2xl bg-orange-500 shadow-xl shadow-orange-500/30 mx-auto">
              <Wind className="h-8 w-8 text-white" />
            </div>

            <div>
              <h1 className="text-2xl font-bold text-white tracking-tight">
                {APP_TITLE}
              </h1>
              <p className="mt-1 text-sm text-slate-400">
                Meridian Data Labs &mdash; Industrial Quality Management
              </p>
            </div>
          </div>

          {/* Auth card */}
          <div className="bg-white dark:bg-background rounded-2xl shadow-2xl border border-white/10 dark:border-slate-700/60 overflow-hidden">
            <Outlet />
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="py-4 text-center text-xs text-slate-500 flex-shrink-0 relative">
        <span>
          &copy; {new Date().getFullYear()} Meridian Data Labs &mdash; v
          {APP_VERSION}
        </span>
      </footer>
    </div>
  );
}
