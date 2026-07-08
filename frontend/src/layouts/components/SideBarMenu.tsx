import type { ComponentType } from "react";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Outlet, NavLink, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { useAuthStore } from "@/store/authStore";
import { useNotificationStore } from "@/store/notificationStore";
import { useUIStore } from "@/store/uiStore";
import { notificationService } from "@/services/notificationService";
import { Button } from "@/components/ui/button";
import KTIcon from "@/components/common/KTIcon";
import {
  DashboardIcon,
  BatchOverviewIcon,
  SettingsIcon,
  AssemblyQueueIcon,
  SlotAllocationIcon,
  BladeEntryIcon,
  OhQueueIcon,
  RockingCreepIcon,
  NotepadIcon,
  UserManagementIcon,
  BellIcon,
} from "@/components/common/CustomIcons";
import { cn } from "@/utils/cn";
import type { UserRole, Notification } from "@/types";
import Navbar from "./Navbar/Navbar";
import Footer from "./Navbar/Footer";

/* ─── Nav items definition ───────────────────────────────────────────────── */

interface NavItem {
  label: string;
  href: string;
  iconName: string;
  icon?: ComponentType<{ className?: string }>;
  roles?: UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Dashboard",
    href: "/dashboard",
    iconName: "chart-simple",
    icon: DashboardIcon,
    roles: ["SUPER_ADMIN"],
  },
  {
    label: "Batch Overview",
    href: "/batch-tracking",
    iconName: "package",
    icon: BatchOverviewIcon,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "ASSEMBLY_OPERATOR", "QA_VIEWER"],
  },
  {
    label: "Assembly Queue",
    href: "/assembly-queue",
    iconName: "cube-3",
    icon: AssemblyQueueIcon,
    roles: ["SUPER_ADMIN", "ASSEMBLY_OPERATOR"],
  },
  {
    label: "Slot Allocation",
    href: "/slots",
    iconName: "geolocation",
    icon: SlotAllocationIcon,
    roles: ["SUPER_ADMIN", "ASSEMBLY_OPERATOR"],
  },
  {
    label: "Blade Entry",
    href: "/blades/new",
    iconName: "wrench",
    icon: BladeEntryIcon,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "QA_VIEWER"],
  },
  {
    label: "OH Queue",
    href: "/oh-queue",
    iconName: "book-open",
    icon: OhQueueIcon,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "QA_VIEWER"],
  },
  {
    label: "Rocking & Creep",
    href: "/rocking-creep",
    iconName: "flask",
    icon: RockingCreepIcon,
    roles: ["SUPER_ADMIN", "OH_OPERATOR"],
  },
  {
    label: "Reports",
    href: "/reports",
    iconName: "graph-up",
    icon: NotepadIcon,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "QA_VIEWER"],
  },
  { label: "Notifications", href: "/notifications", iconName: "notification", icon: BellIcon },
  {
    label: "User Management",
    href: "/users",
    iconName: "people",
    icon: UserManagementIcon,
    roles: ["SUPER_ADMIN"],
  },
  {
    label: "Settings",
    href: "/settings",
    iconName: "setting-4",
    icon: SettingsIcon,
  },
];

/* ─── WebSocket singleton ─────────────────────────────────────────────────── */

const WS_URL = (import.meta.env.VITE_WS_URL as string | undefined) ?? "ws://localhost:8000";

function connectWebSocket(
  token: string,
  onMessage: (notification: Notification) => void,
  onClose?: () => void
): WebSocket {
  const ws = new WebSocket(`${WS_URL}/ws/notifications?token=${token}`);

  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data as string);
      // Backend sends { event: "notification", data: {...} }
      const msgType = payload.type ?? payload.event;
      if (msgType === "notification" && payload.data) {
        onMessage(payload.data as Notification);
      } else if (msgType === "ping") {
        ws.send(JSON.stringify({ type: "pong" }));
      }
    } catch {
      // ignore malformed frames
    }
  };

  ws.onclose = () => onClose?.();

  return ws;
}

/* ─── Sidebar nav link ────────────────────────────────────────────────────── */

function SideNavLink({
  item,
  collapsed,
  onClick,
}: {
  item: NavItem;
  collapsed: boolean;
  onClick?: () => void;
}) {
  return (
    <NavLink
      to={item.href}
      end={item.href === "/"}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-semibold transition-colors group relative",
          isActive 
            ? "bg-orange-50 dark:bg-orange-500/10 text-slate-900 dark:text-white" 
            : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800"
        )
      }
    >
      {({ isActive }) => (
        <>
          {item.icon ? (
            <item.icon
              className={cn(
                "text-xl leading-none flex-shrink-0 transition-colors",
                isActive 
                  ? "text-slate-900 dark:text-white" 
                  : "text-slate-400 dark:text-slate-500 group-hover:text-slate-900 dark:group-hover:text-white"
              )}
            />
          ) : (
            <KTIcon
              iconName={item.iconName}
              className={cn(
                "text-xl leading-none flex-shrink-0 transition-colors",
                isActive 
                  ? "text-slate-900 dark:text-white" 
                  : "text-slate-400 dark:text-slate-500 group-hover:text-slate-900 dark:group-hover:text-white"
              )}
            />
          )}
          {!collapsed && <span className="truncate">{item.label}</span>}
          {collapsed && (
            <span className="absolute left-full ml-2 px-2 py-1 rounded-lg bg-slate-800 text-white text-xs shadow-lg border border-slate-700 opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50 transition-opacity">
              {item.label}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}

/* ─── Main layout ─────────────────────────────────────────────────────────── */

export default function AppLayout() {
  const { user } = useAuthStore();
  const { addNotification, setNotifications } = useNotificationStore();
  const { sidebarCollapsed, toggleSidebar, theme } = useUIStore();

  /* ── Hover-to-expand when collapsed (desktop) ── */
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const showExpanded = !sidebarCollapsed || sidebarHovered;

  function handleToggleSidebar() {
    toggleSidebar();
    setSidebarHovered(false);
  }

  // Poll unread count every 30 s so the bell badge stays current without visiting NotificationsPage
  useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: async () => {
      const count = await notificationService.getUnreadCount();
      // Also sync the full list so the store is populated
      if (count > 0) {
        const items = await notificationService.list({ page_size: 50 });
        setNotifications(items);
      }
      return count;
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const navigate = useNavigate();

  const [mobileOpen, setMobileOpen] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  /* ── WebSocket connect on mount ── */
  useEffect(() => {
    const token = useAuthStore.getState().accessToken;
    if (!token) return;

    function connect() {
      wsRef.current = connectWebSocket(
        token!,
        (notification) => {
          addNotification(notification);
          toast(notification.title, {
            description: notification.body,
            action: notification.blade_id
              ? {
                label: "View",
                onClick: () => navigate(`/blades/${notification.blade_id}`),
              }
              : undefined,
          });
        },
        () => {
          // Reconnect after 5 s on unexpected close
          setTimeout(connect, 5000);
        }
      );
    }

    connect();

    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Filtered nav items ── */
  const visibleNav = NAV_ITEMS.filter((item) => {
    if (!item.roles) return true;
    return item.roles.some((r) => user?.roles.includes(r));
  });

  /* ── Close mobile sidebar on route change ── */
  const location = useLocation();
  const isFullScreenPage =
    location.pathname === "/dashboard" ||
    location.pathname === "/batch-tracking" ||
    location.pathname === "/assembly-queue" ||
    location.pathname === "/oh-queue" ||
    location.pathname === "/slots" ||
    location.pathname === "/notifications" ||
    location.pathname === "/reports" ||
    location.pathname === "/users" ||
    location.pathname === "/settings" ||
    location.pathname === "/rocking-creep" ||
    location.pathname.startsWith("/assembly/") ||
    location.pathname.startsWith("/blades/") ||
    location.pathname.startsWith("/batches/");
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  /* ──────────────────────────────────────────────────── */
  /* Sidebar content (shared between desktop and mobile) */
  /* ──────────────────────────────────────────────────── */
  function SidebarContent({ mobile = false }: { mobile?: boolean }) {
    const collapsedView = !mobile && !showExpanded;
    return (
      <div className="flex flex-col h-full bg-white dark:bg-black">
        {/* Logo */}
        <div
          className={cn(
            "flex items-center gap-2.5 px-4 h-14 sm:h-16 border-b border-slate-200 dark:border-slate-700 flex-shrink-0 bg-white dark:bg-black",
            collapsedView ? "justify-center px-2" : "justify-between"
          )}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <img
              src={theme === "dark" ? "/media/login/Dark.png" : "/media/login/Light.png"}
              alt="Blade Rocking & Creep Test System"
              className="h-10 w-10 sm:h-14 sm:w-14 object-contain flex-shrink-0"
            />
            {!collapsedView && (
              <span className="font-bold text-base text-slate-900 dark:text-white tracking-tight truncate min-w-0">
                BRCMS
              </span>
            )}
          </div>

          {/* Collapse toggle (desktop only, expanded state) */}
          {!mobile && showExpanded && (
            <div className="flex items-center ml-3 pl-3 border-l border-dashed border-slate-200 dark:border-slate-700 flex-shrink-0">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 flex-shrink-0 rounded-lg bg-slate-100 text-slate-500 hover:bg-slate-200 hover:text-slate-900 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600 dark:hover:text-white"
                onClick={handleToggleSidebar}
                aria-label="Collapse sidebar"
              >
                <KTIcon iconName="black-left" className="text-base leading-none" />
              </Button>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 px-2.5 space-y-1 bg-white dark:bg-black">
          {visibleNav.map((item) => (
            <SideNavLink
              key={item.href}
              item={item}
              collapsed={collapsedView}
              onClick={mobile ? () => setMobileOpen(false) : undefined}
            />
          ))}
        </nav>

      </div>
    );
  }

  return (
    <div className="flex h-screen bg-slate-100 dark:bg-black overflow-hidden">
      {/* ── Desktop sidebar ── */}
      <aside
        onMouseEnter={() => sidebarCollapsed && setSidebarHovered(true)}
        onMouseLeave={() => setSidebarHovered(false)}
        className={cn(
          "hidden lg:flex relative flex-col border-r border-slate-200 dark:border-slate-700 bg-white dark:bg-black transition-all duration-200 flex-shrink-0",
          showExpanded ? "w-56" : "w-16"
        )}
      >
        <SidebarContent />

        {/* Floating expand toggle (idle collapsed state only) */}
        {sidebarCollapsed && !sidebarHovered && (
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-6 right-0 translate-x-1/2 h-7 w-7 rounded-lg bg-slate-100 text-slate-500 border border-slate-200 shadow-sm hover:bg-slate-200 hover:text-slate-900 dark:bg-slate-700 dark:text-slate-300 dark:border-slate-600 dark:hover:bg-slate-600 dark:hover:text-white z-10"
            onClick={handleToggleSidebar}
            aria-label="Expand sidebar"
          >
            <KTIcon iconName="black-right" className="text-sm leading-none" />
          </Button>
        )}
      </aside>

      {/* ── Mobile sidebar overlay ── */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          {/* Drawer */}
          <aside className="absolute left-0 top-0 bottom-0 w-48 bg-white dark:bg-black border-r border-slate-200 dark:border-slate-700 z-50 flex flex-col">
            <div className="flex items-center justify-between px-4 h-16 border-b border-slate-100 dark:border-slate-700 bg-white dark:bg-black">
              <span className="font-bold text-sm text-slate-900 dark:text-white">Navigation</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setMobileOpen(false)}
                className="text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                aria-label="Close menu"
              >
                <KTIcon iconName="cross" className="text-base leading-none" />
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <SidebarContent mobile />
            </div>
          </aside>
        </div>
      )}

      {/* ── Main area ── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Navbar onOpenMobileMenu={() => setMobileOpen(true)} />

        {/* ── Page content ── */}
        {isFullScreenPage ? (
          <main className="flex-1 min-h-0 overflow-hidden bg-slate-100 dark:bg-black">
            <Outlet />
          </main>
        ) : (
          <main className="flex-1 min-h-0 flex flex-col bg-slate-100 dark:bg-black">
            <div className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8">
              <Outlet />
            </div>
            <div className="shrink-0 p-4 pt-2 md:px-6 lg:px-8 border-t border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-black">
              <Footer />
            </div>
          </main>
        )}
      </div>
    </div>
  );
}
