import { useNavigate } from "react-router-dom";

import { useAuthStore } from "@/store/authStore";
import { NotificationsDropdown } from "./NotificationsDropdown";
import { useNotificationStore } from "@/store/notificationStore";
import { useUIStore } from "@/store/uiStore";
import { Button } from "@/components/ui/button";
import KTIcon from "@/components/common/KTIcon";
import { BellIcon, MoonIcon } from "@/components/common/CustomIcons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { UserRole } from "@/types";

/* ─── Role badge ─────────────────────────────────────────────────────────── */

const ROLE_LABEL: Record<UserRole, string> = {
  SUPER_ADMIN: "Super Admin",
  OH_OPERATOR: "OH Operator",
  ASSEMBLY_OPERATOR: "Assembly Operator",
  QA_VIEWER: "QA Viewer",
};

/* ─── Navbar ─────────────────────────────────────────────────────────────── */

export default function Navbar({ onOpenMobileMenu }: { onOpenMobileMenu: () => void }) {
  const { user, logout } = useAuthStore();
  const { unreadCount } = useNotificationStore();
  const { theme, toggleTheme } = useUIStore();

  const navigate = useNavigate();

  const primaryRole = user?.roles[0];

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <header className="flex items-center justify-between h-14 sm:h-16 px-3 sm:px-6 bg-white dark:bg-black border-b border-slate-200 dark:border-slate-700 flex-shrink-0 gap-2">
      {/* Left: hamburger */}
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
      </div>

      {/* Right: notification bell + theme toggle + user dropdown */}
      <div className="flex items-center gap-1.5 sm:gap-3 flex-shrink-0">
        <NotificationsDropdown />

        {/* Theme toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          className="h-11 w-11 rounded-lg bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? (
            <MoonIcon className="text-xl sm:text-[22px] leading-none" />
          ) : (
            <KTIcon iconName="sun" className="text-xl sm:text-[22px] leading-none" />
          )}
        </Button>

        {/* User dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 shrink-0 aspect-square p-0 rounded-lg overflow-hidden hover:bg-slate-100 dark:hover:bg-slate-700"
              aria-label="User menu"
            >
              <img
                src="/media/avatars/Avatar.png"
                alt="Avatar"
                className="h-11 w-11 aspect-square rounded-lg object-cover flex-shrink-0 scale-125 bg-slate-200 dark:bg-slate-800"
              />
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-60 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 shadow-xl rounded-xl p-2">
            <DropdownMenuLabel className="font-normal p-2">
              <div className="flex flex-col gap-1">
                <span className="font-semibold text-sm truncate text-slate-900 dark:text-white">
                  {user?.full_name || user?.username}
                </span>
                <span className="text-xs text-slate-500 dark:text-slate-400 truncate">
                  {user?.email}
                </span>
                {primaryRole && (
                  <span className="mt-1 inline-block text-[10px] font-bold uppercase tracking-wide bg-orange-50 dark:bg-orange-500/10 text-orange-600 dark:text-orange-400 px-2 py-0.5 rounded-md w-fit">
                    {ROLE_LABEL[primaryRole]}
                  </span>
                )}
              </div>
            </DropdownMenuLabel>

            <DropdownMenuSeparator className="bg-slate-100 dark:bg-slate-800 my-1" />

            <DropdownMenuItem onClick={() => navigate("/profile")} className="text-slate-700 dark:text-slate-300 focus:bg-slate-100 dark:focus:bg-slate-800 rounded-lg cursor-pointer py-2.5 px-3">
              <KTIcon iconName="user-square" className="mr-2.5 text-[1.15rem] leading-none text-slate-400 dark:text-slate-500" />
              <span className="font-medium text-sm">My Profile</span>
            </DropdownMenuItem>

            <DropdownMenuItem onClick={() => navigate("/settings#security")} className="text-slate-700 dark:text-slate-300 focus:bg-slate-100 dark:focus:bg-slate-800 rounded-lg cursor-pointer py-2.5 px-3">
              <KTIcon iconName="key" className="mr-2.5 text-[1.15rem] leading-none text-slate-400 dark:text-slate-500" />
              <span className="font-medium text-sm">Change Password</span>
            </DropdownMenuItem>

            <DropdownMenuSeparator className="bg-slate-100 dark:bg-slate-800 my-1" />

            <DropdownMenuItem
              onClick={handleLogout}
              className="text-red-600 dark:text-red-400 focus:text-red-600 focus:bg-red-50 dark:focus:text-red-400 dark:focus:bg-red-500/10 rounded-lg cursor-pointer py-2.5 px-3"
            >
              <KTIcon iconName="exit-right" className="mr-2.5 text-[1.15rem] leading-none" />
              <span className="font-medium text-sm">Logout</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
