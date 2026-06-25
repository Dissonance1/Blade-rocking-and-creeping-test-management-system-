import { RouterProvider, createBrowserRouter, Navigate } from "react-router-dom";
import AppLayout from "@/layouts/AppLayout";
import AuthLayout from "@/layouts/AuthLayout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import BladeEntryPage from "@/pages/BladeEntryPage";
import BladeDetailPage from "@/pages/BladeDetailPage";
import WorkflowTimelinePage from "@/pages/WorkflowTimelinePage";
import OHQueuePage from "@/pages/OHQueuePage";
import AssemblyQueuePage from "@/pages/AssemblyQueuePage";
import SlotAllocationPage from "@/pages/SlotAllocationPage";
import ReportsPage from "@/pages/ReportsPage";
import UserManagementPage from "@/pages/UserManagementPage";

import NotificationsPage from "@/pages/NotificationsPage";
import SettingsPage from "@/pages/SettingsPage";
import BatchTrackingPage from "@/pages/BatchTrackingPage";
import ModifyBatchPage from "@/pages/ModifyBatchPage";
import AcceptBatchPage from "@/pages/AcceptBatchPage";
import RockingCreepPage from "@/pages/RockingCreepPage";
import { useAuthStore } from "@/store/authStore";

/* ─── Auth guard ─────────────────────────────────────────────────────────── */

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

/* ─── Router ─────────────────────────────────────────────────────────────── */

const router = createBrowserRouter([
  /* ── Auth routes (no app shell) ── */
  {
    element: <AuthLayout />,
    children: [{ path: "/login", element: <LoginPage /> }],
  },

  /* ── App routes (protected — redirect to /login if not authenticated) ── */
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/blades/new", element: <BladeEntryPage /> },
      { path: "/blades/:id", element: <BladeDetailPage /> },
      { path: "/blades/:id/timeline", element: <WorkflowTimelinePage /> },
      { path: "/oh-queue", element: <OHQueuePage /> },
      { path: "/oh/queue", element: <Navigate to="/oh-queue" replace /> },
      { path: "/assembly-queue", element: <AssemblyQueuePage /> },
      { path: "/assembly/queue", element: <Navigate to="/assembly-queue" replace /> },
      { path: "/slots", element: <SlotAllocationPage /> },
      { path: "/assembly/slots", element: <Navigate to="/slots" replace /> },
      { path: "/reports", element: <ReportsPage /> },
      { path: "/users", element: <UserManagementPage /> },
      { path: "/admin/users", element: <Navigate to="/users" replace /> },

      { path: "/batch-tracking", element: <BatchTrackingPage /> },
      { path: "/batches/:batchNumber/modify", element: <ModifyBatchPage /> },
      { path: "/batches/:batchNumber/accept", element: <AcceptBatchPage /> },
      { path: "/rocking-creep", element: <RockingCreepPage /> },
      { path: "/notifications", element: <NotificationsPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "/dashboard", element: <Navigate to="/" replace /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

export default function AppRouter() {
  return <RouterProvider router={router} />;
}
