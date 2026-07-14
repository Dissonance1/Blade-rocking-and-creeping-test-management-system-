import { RouterProvider, createBrowserRouter, Navigate, useNavigate } from "react-router-dom";
import AppLayout from "@/layouts/components/SideBarMenu";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import QaDashboardPage from "@/pages/QaDashboardPage";
import BladeEntryPage from "@/pages/BladeEntryPage";
import BladeDetailPage from "@/pages/BladeDetailPage";
import WorkflowTimelinePage from "@/pages/WorkflowTimelinePage";
import OHQueuePage from "@/pages/OHQueuePage";
import AssemblyQueuePage from "@/pages/AssemblyQueuePage";
import SlotAllocationPage from "@/pages/SlotAllocationPage";
import OHSlotAllocationPage from "@/pages/OHSlotAllocationPage";
import ReportsPage from "@/pages/ReportsPage";
import UserManagementPage from "@/pages/UserManagementPage";

import NotificationsPage from "@/pages/NotificationsPage";
import SettingsPage from "@/pages/SettingsPage";
import BatchTrackingPage from "@/pages/BatchTrackingPage";
import ModifyBatchPage from "@/pages/ModifyBatchPage";
import AcceptBatchPage from "@/pages/AcceptBatchPage";
import RockingCreepPage from "@/pages/RockingCreepPage";
import AssemblyVerificationPage from "@/pages/AssemblyVerificationPage";
import MyProfile from "@/pages/MyProfile";
import { useAuthStore } from "@/store/authStore";
import type { UserRole } from "@/types";
import { ShieldOff, ArrowLeft } from "lucide-react";
import RouteErrorBoundary from "@/components/common/RouteErrorBoundary";

/* ─── Auth guard ─────────────────────────────────────────────────────────── */

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function AccessDenied({ requiredRoles }: { requiredRoles: UserRole[] }) {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const currentRole = user?.roles?.[0] ?? "Unknown";

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-background flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-white dark:bg-background rounded-2xl shadow-xl border border-slate-200 dark:border-slate-700 p-8 text-center">
        <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-4">
          <ShieldOff className="w-8 h-8 text-red-500" />
        </div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-white mb-2">
          Access Denied
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">
          You don't have permission to view this page.
          <br />
          <span className="mt-2 block">
            Your role:{" "}
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              {currentRole.replace(/_/g, " ")}
            </span>
          </span>
          <span className="mt-1 block text-xs">
            Required:{" "}
            <span className="font-semibold text-slate-600 dark:text-slate-400">
              {requiredRoles.map((r) => r.replace(/_/g, " ")).join(" or ")}
            </span>
          </span>
        </p>
        <button
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-orange-500 hover:bg-orange-400 text-white text-sm font-semibold transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Go Back
        </button>
      </div>
    </div>
  );
}

function RequireRole({
  roles,
  children,
}: {
  roles: UserRole[];
  children: React.ReactNode;
}) {
  const hasRole = useAuthStore((s) => s.hasRole);
  if (!hasRole(roles)) {
    return <AccessDenied requiredRoles={roles} />;
  }
  return <>{children}</>;
}

/* ─── Role home ──────────────────────────────────────────────────────────── */

/** Maps a role to its landing path. Export so LoginPage can use it too. */
export function getRoleHomePath(roles: UserRole[]): string {
  if (roles.includes("SUPER_ADMIN")) return "/dashboard";
  if (roles.includes("QA_VIEWER")) return "/qa-dashboard";
  return "/batch-tracking";
}

function RoleHome() {
  const user = useAuthStore((s) => s.user);
  const dest = getRoleHomePath(user?.roles ?? []);
  return <Navigate to={dest} replace />;
}

/* ─── Router ─────────────────────────────────────────────────────────────── */

const router = createBrowserRouter([
  /* ── Auth routes (no app shell) ── */
  { path: "/login", element: <LoginPage />, errorElement: <RouteErrorBoundary /> },

  /* ── App routes (protected — redirect to /login if not authenticated) ── */
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: "/", element: <RoleHome /> },
      {
        path: "/dashboard",
        element: (
          <RequireRole roles={["SUPER_ADMIN"]}>
            <DashboardPage />
          </RequireRole>
        ),
      },
      {
        path: "/qa-dashboard",
        element: (
          <RequireRole roles={["QA_VIEWER", "SUPER_ADMIN"]}>
            <QaDashboardPage />
          </RequireRole>
        ),
      },
      {
        path: "/blades/new",
        element: (
          <RequireRole roles={["OH_OPERATOR", "SUPER_ADMIN"]}>
            <BladeEntryPage />
          </RequireRole>
        ),
      },
      {
        path: "/blades/:workOrderNumber/entry",
        element: (
          <RequireRole roles={["OH_OPERATOR", "SUPER_ADMIN"]}>
            <BladeEntryPage />
          </RequireRole>
        ),
      },
      { path: "/blades/:id", element: <BladeDetailPage /> },
      { path: "/blades/:id/timeline", element: <WorkflowTimelinePage /> },
      {
        path: "/oh-queue",
        element: (
          <RequireRole roles={["OH_OPERATOR", "SUPER_ADMIN"]}>
            <OHQueuePage />
          </RequireRole>
        ),
      },
      { path: "/oh/queue", element: <Navigate to="/oh-queue" replace /> },
      {
        path: "/assembly-queue",
        element: (
          <RequireRole roles={["ASSEMBLY_OPERATOR", "SUPER_ADMIN"]}>
            <AssemblyQueuePage />
          </RequireRole>
        ),
      },
      { path: "/assembly/queue", element: <Navigate to="/assembly-queue" replace /> },
      {
        path: "/slots",
        element: (
          <RequireRole roles={["ASSEMBLY_OPERATOR", "SUPER_ADMIN"]}>
            <SlotAllocationPage />
          </RequireRole>
        ),
      },
      { path: "/assembly/slots", element: <Navigate to="/slots" replace /> },
      {
        path: "/oh/slot-allocation",
        element: (
          <RequireRole roles={["OH_OPERATOR", "SUPER_ADMIN"]}>
            <OHSlotAllocationPage />
          </RequireRole>
        ),
      },
      { path: "/reports", element: <ReportsPage /> },
      {
        path: "/users",
        element: (
          <RequireRole roles={["SUPER_ADMIN"]}>
            <UserManagementPage />
          </RequireRole>
        ),
      },
      { path: "/admin/users", element: <Navigate to="/users" replace /> },

      { path: "/profile", element: <MyProfile /> },

      {
        path: "/assembly/verify/:workOrderNumber",
        element: (
          <RequireRole roles={["ASSEMBLY_OPERATOR", "SUPER_ADMIN"]}>
            <AssemblyVerificationPage />
          </RequireRole>
        ),
      },
      { path: "/batch-tracking", element: <BatchTrackingPage /> },
      {
        path: "/batches/:workOrderNumber/modify",
        element: (
          <RequireRole roles={["ASSEMBLY_OPERATOR", "SUPER_ADMIN"]}>
            <ModifyBatchPage />
          </RequireRole>
        ),
      },
      {
        path: "/batches/:workOrderNumber/accept",
        element: (
          <RequireRole roles={["ASSEMBLY_OPERATOR", "SUPER_ADMIN"]}>
            <AcceptBatchPage />
          </RequireRole>
        ),
      },
      {
        path: "/rocking-creep",
        element: (
          <RequireRole roles={["OH_OPERATOR", "SUPER_ADMIN"]}>
            <RockingCreepPage />
          </RequireRole>
        ),
      },
      { path: "/notifications", element: <NotificationsPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

export default function AppRouter() {
  return <RouterProvider router={router} />;
}
