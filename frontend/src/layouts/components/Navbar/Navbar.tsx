import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "@/store/authStore";
import { useNotificationStore } from "@/store/notificationStore";
import { useUIStore } from "@/store/uiStore";
import { Button } from "@/components/ui/button";
import KTIcon from "@/components/common/KTIcon";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/utils/cn";
import type { UserRole } from "@/types";

/* ─── Role badge ─────────────────────────────────────────────────────────── */

const ROLE_LABEL: Record<UserRole, string> = {
  SUPER_ADMIN: "Super Admin",
  OH_OPERATOR: "OH Operator",
  ASSEMBLY_OPERATOR: "Assembly Operator",
  QA_VIEWER: "QA Viewer",
};

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

/* ─── Navbar ─────────────────────────────────────────────────────────────── */

export default function Navbar({ onOpenMobileMenu }: { onOpenMobileMenu: () => void }) {
  const { user, logout } = useAuthStore();
  const { unreadCount } = useNotificationStore();
  const { theme, toggleTheme } = useUIStore();

  const navigate = useNavigate();
  const breadcrumb = useBreadcrumb();

  const primaryRole = user?.roles[0];

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <header className="flex items-center justify-between h-20 px-6 bg-white dark:bg-slate-800 flex-shrink-0 gap-2">
      {/* Left: hamburger + breadcrumb */}
      <div className="flex items-center gap-3 min-w-0">
        {/* Mobile hamburger */}
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden flex-shrink-0 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          onClick={onOpenMobileMenu}
          aria-label="Open menu"
        >
          <KTIcon iconName="burger-menu-2" className="text-xl leading-none" />
        </Button>

        {/* Breadcrumb */}
        <nav
          aria-label="Breadcrumb"
          className="hidden sm:flex items-center gap-1.5 text-base text-slate-400 dark:text-slate-400 min-w-0"
        >
          {breadcrumb.map((crumb, idx) => {
            const isLast = idx === breadcrumb.length - 1;
            return (
              <span key={idx} className="flex items-center gap-1.5 min-w-0">
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
                      isLast ? "text-slate-900 dark:text-white font-bold text-base" : ""
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

      {/* Right: notification bell + theme toggle + user dropdown */}
      <div className="flex items-center gap-3 flex-shrink-0">
        {/* Notification bell */}
        <Button
          variant="ghost"
          size="icon"
          className="relative h-9 w-9 rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-200"
          onClick={() => navigate("/notifications")}
          aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
        >
          <KTIcon iconName="notification" className="text-lg leading-none" />
          {unreadCount > 0 && (
            <span className="absolute top-0.5 right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-[10px] font-bold text-white flex items-center justify-center leading-none">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </Button>

        {/* Theme toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          className="h-9 w-9 rounded-full bg-slate-900 text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900"
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? (
            <KTIcon iconName="sun" className="text-lg leading-none" />
          ) : (
            <KTIcon iconName="moon" className="text-lg leading-none" />
          )}
        </Button>

        {/* User dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
              aria-label="User menu"
            >
              <img
                src="/media/avatars/blank.svg"
                alt=""
                className="h-9 w-9 rounded-lg object-cover flex-shrink-0"
              />
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

            <DropdownMenuItem onClick={() => navigate("/settings#profile")} className="text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 cursor-pointer">
              <KTIcon iconName="user-square" className="mr-2 text-lg leading-none" />
              My Profile
            </DropdownMenuItem>

            <DropdownMenuItem onClick={() => navigate("/settings#security")} className="text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 cursor-pointer">
              <KTIcon iconName="key" className="mr-2 text-lg leading-none" />
              Change Password
            </DropdownMenuItem>

            <DropdownMenuSeparator className="bg-slate-200 dark:bg-slate-700" />

            <DropdownMenuItem
              onClick={handleLogout}
              className="text-red-500 focus:text-red-500 focus:bg-red-50 dark:focus:bg-red-500/10 cursor-pointer"
            >
              <KTIcon iconName="exit-right" className="mr-2 text-lg leading-none" />
              Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
