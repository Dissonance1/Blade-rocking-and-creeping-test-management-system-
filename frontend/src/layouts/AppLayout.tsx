import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Outlet, NavLink, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  LayoutDashboard,
  ClipboardList,
  Layers,
  Grid3X3,
  BarChart2,
  Users,
  Settings,
  Bell,
  Menu,
  X,
  Sun,
  Moon,
  LogOut,
  UserCircle,
  KeyRound,
  Wind,
  ChevronRight,
  PackageSearch,
  FlaskConical,
} from "lucide-react";

import { useAuthStore } from "@/store/authStore";
import { useNotificationStore } from "@/store/notificationStore";
import { useUIStore } from "@/store/uiStore";
import { notificationService } from "@/services/notificationService";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/utils/cn";
import type { UserRole, Notification } from "@/types";

/* ─── Nav items definition ───────────────────────────────────────────────── */

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  roles?: UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Batch Overview",
    href: "/batch-tracking",
    icon: PackageSearch,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "ASSEMBLY_OPERATOR", "QA_VIEWER"],
  },
  {
    label: "Assembly Queue",
    href: "/assembly-queue",
    icon: Grid3X3,
    roles: ["SUPER_ADMIN", "ASSEMBLY_OPERATOR"],
  },
  {
    label: "Slot Allocation",
    href: "/slots",
    icon: Grid3X3,
    roles: ["SUPER_ADMIN", "ASSEMBLY_OPERATOR"],
  },
  { label: "Notifications", href: "/notifications", icon: Bell },
  {
    label: "Dashboard",
    href: "/dashboard",
    icon: LayoutDashboard,
    roles: ["SUPER_ADMIN"],
  },
  {
    label: "Blade Entry",
    href: "/blades/new",
    icon: ClipboardList,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "QA_VIEWER"],
  },
  {
    label: "OH Queue",
    href: "/oh-queue",
    icon: Layers,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "QA_VIEWER"],
  },
  {
    label: "Rocking & Creep",
    href: "/rocking-creep",
    icon: FlaskConical,
    roles: ["SUPER_ADMIN", "OH_OPERATOR"],
  },
  {
    label: "Reports",
    href: "/reports",
    icon: BarChart2,
    roles: ["SUPER_ADMIN", "OH_OPERATOR", "QA_VIEWER"],
  },
  {
    label: "User Management",
    href: "/users",
    icon: Users,
    roles: ["SUPER_ADMIN"],
  },
  {
    label: "Settings",
    href: "/settings",
    icon: Settings,
    roles: ["SUPER_ADMIN"],
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

/* ─── Breadcrumb helper ───────────────────────────────────────────────────── */

function useBreadcrumb(): { label: string; href?: string }[] {
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);

  if (segments.length === 0) return [{ label: "Home" }];

  const labelMap: Record<string, string> = {
    blades: "Blades",
    new: "New Entry",
    "oh-queue": "OH Queue",
    "assembly-queue": "Assembly Queue",
    slots: "Slot Allocation",
    "batch-tracking": "Batch Overview",
    batches: "Batches",
    modify: "Modify Batch",
    accept: "Accept Batch",
    reports: "Reports",

    users: "User Management",
    settings: "Settings",
    notifications: "Notifications",
    timeline: "Timeline",
    "rocking-creep": "Rocking & Creep",
  };

  const crumbs: { label: string; href?: string }[] = [
    { label: "Home", href: "/" },
  ];

  let accPath = "";
  segments.forEach((seg, idx) => {
    accPath += `/${seg}`;
    const isLast = idx === segments.length - 1;
    const label = labelMap[seg] ?? seg;
    crumbs.push(isLast ? { label } : { label, href: accPath });
  });

  return crumbs;
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
  const Icon = item.icon;

  return (
    <NavLink
      to={item.href}
      end={item.href === "/"}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors group relative",
          isActive
            ? "bg-orange-500 text-white"
            : "text-slate-400 hover:text-white hover:bg-slate-700/60"
        )
      }
    >
      <Icon className="h-4 w-4 flex-shrink-0" />
      {!collapsed && <span className="truncate">{item.label}</span>}
      {collapsed && (
        <span className="absolute left-full ml-2 px-2 py-1 rounded-lg bg-slate-800 text-white text-xs shadow-lg border border-slate-700 opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50 transition-opacity">
          {item.label}
        </span>
      )}
    </NavLink>
  );
}

/* ─── Role badge ─────────────────────────────────────────────────────────── */

const ROLE_LABEL: Record<UserRole, string> = {
  SUPER_ADMIN: "Super Admin",
  OH_OPERATOR: "OH Operator",
  ASSEMBLY_OPERATOR: "Assembly Operator",
  QA_VIEWER: "QA Viewer",
};

/* ─── Main layout ─────────────────────────────────────────────────────────── */

export default function AppLayout() {
  const { user, logout } = useAuthStore();
  const { unreadCount, addNotification, setNotifications } = useNotificationStore();
  const { sidebarCollapsed, theme, toggleSidebar, toggleTheme } = useUIStore();

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
  const breadcrumb = useBreadcrumb();

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

  /* ── User initials ── */
  const initials = user
    ? (user.full_name || user.username)
        .split(" ")
        .slice(0, 2)
        .map((w) => w[0])
        .join("")
        .toUpperCase()
    : "U";

  const primaryRole = user?.roles[0];

  /* ── Close mobile sidebar on route change ── */
  const location = useLocation();
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  /* ── Logout ── */
  function handleLogout() {
    logout();
    navigate("/login");
  }

  const appVersion = (import.meta.env.VITE_APP_VERSION as string | undefined) ?? "1.0.0";

  /* ──────────────────────────────────────────────────── */
  /* Sidebar content (shared between desktop and mobile) */
  /* ──────────────────────────────────────────────────── */
  function SidebarContent({ mobile = false }: { mobile?: boolean }) {
    return (
      <div className="flex flex-col h-full bg-slate-900">
        {/* Logo */}
        <div
          className={cn(
            "flex items-center gap-2 px-3 h-16 border-b border-slate-800 flex-shrink-0 bg-slate-950",
            !mobile && sidebarCollapsed ? "justify-center" : ""
          )}
        >
          <div className="h-8 w-8 rounded-lg bg-orange-500 flex items-center justify-center flex-shrink-0">
            <Wind className="h-4 w-4 text-white" />
          </div>
          {(!sidebarCollapsed || mobile) && (
            <span className="font-bold text-sm leading-tight truncate text-white">
              Blade<br />
              <span className="font-normal text-slate-400 text-xs">
                Test Management
              </span>
            </span>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-0.5 bg-slate-900">
          {visibleNav.map((item) => (
            <SideNavLink
              key={item.href}
              item={item}
              collapsed={!mobile && sidebarCollapsed}
              onClick={mobile ? () => setMobileOpen(false) : undefined}
            />
          ))}
        </nav>

        {/* Bottom: collapse toggle (desktop only) */}
        {!mobile && (
          <div className="border-t border-slate-800 px-2 py-3 bg-slate-900">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-center text-slate-400 hover:text-white hover:bg-slate-700/60"
              onClick={toggleSidebar}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              <ChevronRight
                className={cn(
                  "h-4 w-4 transition-transform",
                  !sidebarCollapsed && "rotate-180"
                )}
              />
              {!sidebarCollapsed && (
                <span className="ml-2 text-xs">Collapse</span>
              )}
            </Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-slate-100 dark:bg-slate-900 overflow-hidden">
      {/* ── Desktop sidebar ── */}
      <aside
        className={cn(
          "hidden lg:flex flex-col border-r border-slate-800 bg-slate-900 transition-all duration-200 flex-shrink-0",
          sidebarCollapsed ? "w-14" : "w-56"
        )}
      >
        <SidebarContent />
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
          <aside className="absolute left-0 top-0 bottom-0 w-64 bg-slate-900 border-r border-slate-800 z-50 flex flex-col">
            <div className="flex items-center justify-between px-4 h-16 border-b border-slate-800 bg-slate-950">
              <span className="font-bold text-sm text-white">Navigation</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setMobileOpen(false)}
                className="text-slate-400 hover:text-white"
                aria-label="Close menu"
              >
                <X className="h-4 w-4" />
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
        {/* ── Header ── */}
        <header className="flex items-center justify-between h-16 px-4 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-sm flex-shrink-0 gap-2">
          {/* Left: hamburger + breadcrumb */}
          <div className="flex items-center gap-3 min-w-0">
            {/* Mobile hamburger */}
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden flex-shrink-0 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
              onClick={() => setMobileOpen(true)}
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </Button>

            {/* Desktop sidebar toggle */}
            <Button
              variant="ghost"
              size="icon"
              className="hidden lg:flex flex-shrink-0 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
              onClick={toggleSidebar}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              <Menu className="h-5 w-5" />
            </Button>

            {/* Breadcrumb */}
            <nav
              aria-label="Breadcrumb"
              className="hidden sm:flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 min-w-0"
            >
              {breadcrumb.map((crumb, idx) => {
                const isLast = idx === breadcrumb.length - 1;
                return (
                  <span key={idx} className="flex items-center gap-1 min-w-0">
                    {idx > 0 && (
                      <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-slate-400 dark:text-slate-600" />
                    )}
                    {crumb.href && !isLast ? (
                      <NavLink
                        to={crumb.href}
                        className="hover:text-slate-900 dark:hover:text-white transition-colors truncate"
                      >
                        {crumb.label}
                      </NavLink>
                    ) : (
                      <span
                        className={cn(
                          "truncate",
                          isLast ? "text-slate-900 dark:text-white font-medium" : ""
                        )}
                      >
                        {crumb.label}
                      </span>
                    )}
                  </span>
                );
              })}
            </nav>
          </div>

          {/* Right: theme toggle + notification bell + user dropdown */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Theme toggle */}
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
              className="text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Moon className="h-4 w-4" />
              )}
            </Button>

            {/* Notification bell */}
            <Button
              variant="ghost"
              size="icon"
              className="relative text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
              onClick={() => navigate("/notifications")}
              aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
            >
              <Bell className="h-4 w-4" />
              {unreadCount > 0 && (
                <span className="absolute top-1.5 right-1.5 h-4 w-4 rounded-full bg-orange-500 text-[10px] font-bold text-white flex items-center justify-center leading-none">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </Button>

            {/* User dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  className="flex items-center gap-2 px-2 hover:bg-slate-100 dark:hover:bg-slate-700"
                  aria-label="User menu"
                >
                  <Avatar className="h-7 w-7">
                    <AvatarFallback className="text-xs bg-orange-500 text-white">
                      {initials}
                    </AvatarFallback>
                  </Avatar>
                  <span className="hidden md:block text-sm font-medium max-w-[120px] truncate text-slate-700 dark:text-slate-200">
                    {user?.full_name || user?.username}
                  </span>
                </Button>
              </DropdownMenuTrigger>

              <DropdownMenuContent align="end" className="w-56 bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 shadow-lg">
                <DropdownMenuLabel className="font-normal">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-semibold text-sm truncate text-slate-900 dark:text-white">
                      {user?.full_name || user?.username}
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400 truncate">
                      {user?.email}
                    </span>
                    {primaryRole && (
                      <span className="mt-1 inline-block text-[10px] font-medium uppercase tracking-wide bg-orange-500/10 text-orange-600 dark:text-orange-400 px-1.5 py-0.5 rounded-sm w-fit">
                        {ROLE_LABEL[primaryRole]}
                      </span>
                    )}
                  </div>
                </DropdownMenuLabel>

                <DropdownMenuSeparator className="bg-slate-200 dark:bg-slate-700" />

                <DropdownMenuItem onClick={() => navigate("/profile")} className="text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 cursor-pointer">
                  <UserCircle className="mr-2 h-4 w-4" />
                  My Profile
                </DropdownMenuItem>

                <DropdownMenuItem onClick={() => navigate("/change-password")} className="text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 cursor-pointer">
                  <KeyRound className="mr-2 h-4 w-4" />
                  Change Password
                </DropdownMenuItem>

                <DropdownMenuSeparator className="bg-slate-200 dark:bg-slate-700" />

                <DropdownMenuItem
                  onClick={handleLogout}
                  className="text-red-500 focus:text-red-500 focus:bg-red-50 dark:focus:bg-red-500/10 cursor-pointer"
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Logout
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {/* ── Page content ── */}
        <main className="flex-1 overflow-y-auto bg-slate-100 dark:bg-slate-900">
          <div className="p-4 md:p-6 lg:p-8 min-h-full">
            <Outlet />
          </div>
        </main>

        {/* ── Footer ── */}
        <footer className="flex items-center justify-between px-4 md:px-6 py-2 border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-500 dark:text-slate-400 flex-shrink-0">
          <span>Meridian Data Labs</span>
          <span>v{appVersion}</span>
        </footer>
      </div>
    </div>
  );
}
