import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { formatDistanceToNow, parseISO, isToday, isYesterday } from "date-fns";
import { Bell, BellOff, CheckCheck, Loader2 } from "lucide-react";

import { notificationService } from "@/services/notificationService";
import { useNotificationStore } from "@/store/notificationStore";
import type { Notification } from "@/types";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/utils/cn";
import KTIcon from "@/components/common/KTIcon";
import { BellIcon } from "@/components/common/CustomIcons";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function NotifIcon({ type }: { type: Notification["notification_type"] }) {
  switch (type) {
    case "SYSTEM_ALERT":
      return (
        <div className="w-8 h-8 rounded-full bg-red-100 dark:bg-red-500/20 text-red-500 flex items-center justify-center shrink-0">
          <KTIcon iconName="warning-2" className="text-lg leading-none" />
        </div>
      );
    case "BLADE_READY_FOR_ASSEMBLY":
      return (
        <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-500/20 text-blue-500 flex items-center justify-center shrink-0">
          <KTIcon iconName="send" className="text-lg leading-none ml-0.5" />
        </div>
      );
    case "ASSEMBLY_RECEIVED":
      return (
        <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-500/20 text-indigo-500 flex items-center justify-center shrink-0">
          <KTIcon iconName="verify" className="text-lg leading-none" />
        </div>
      );
    default:
      return (
        <div className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500 flex items-center justify-center shrink-0">
          <Bell className="w-4 h-4" />
        </div>
      );
  }
}

function groupByDate(notifications: Notification[]) {
  const groups: Record<string, Notification[]> = {};
  for (const n of notifications) {
    const d = parseISO(n.created_at);
    let key = "Older";
    if (isToday(d)) key = "Today";
    else if (isYesterday(d)) key = "Yesterday";
    else key = d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key]!.push(n);
  }
  return groups;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function NotificationsDropdown() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const setNotifications = useNotificationStore((s) => s.setNotifications);
  const storeMarkAsRead = useNotificationStore((s) => s.markAsRead);
  const storeMarkAllRead = useNotificationStore((s) => s.markAllAsRead);
  const unreadCount = useNotificationStore((s) => s.unreadCount);

  const { data: notifications = [], isLoading } = useQuery<Notification[]>({
    queryKey: ["notifications"],
    queryFn: async () => {
      const data = await notificationService.list();
      // Ensure latest notifications are at the top
      const sorted = [...data].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setNotifications(sorted);
      return sorted;
    },
    refetchInterval: 15_000,
  });

  const markReadMutation = useMutation({
    mutationFn: (id: string) => notificationService.markRead(id),
    onSuccess: (_, id) => {
      storeMarkAsRead(id);
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: notificationService.markAllRead,
    onSuccess: () => {
      storeMarkAllRead();
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const groups = groupByDate(notifications);

  const handleNotificationClick = (n: Notification) => {
    if (!n.is_read) markReadMutation.mutate(n.id);
    if (n.blade_id) navigate(`/blades/${n.blade_id}`);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative h-11 w-11 rounded-lg bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
          aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
        >
          <BellIcon className="text-2xl sm:text-[26px] leading-none" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-[10px] font-bold text-white flex items-center justify-center leading-none shadow-sm ring-2 ring-white dark:ring-slate-900">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-80 sm:w-96 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 shadow-xl rounded-xl p-0">
        <DropdownMenuLabel className="font-normal p-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BellIcon className="text-[22px] text-orange-500 shrink-0" />
            <span className="font-semibold text-slate-900 dark:text-white">Notifications</span>
            {unreadCount > 0 && (
              <span className="rounded-full bg-orange-100 text-orange-600 dark:bg-orange-500/20 dark:text-orange-400 text-[10px] px-2 py-0.5 font-bold tabular-nums">
                {unreadCount} NEW
              </span>
            )}
          </div>
          {unreadCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.preventDefault();
                markAllReadMutation.mutate();
              }}
              disabled={markAllReadMutation.isPending}
              className="h-7 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white px-2"
            >
              {markAllReadMutation.isPending ? (
                <Loader2 className="w-3 h-3 animate-spin mr-1" />
              ) : (
                <CheckCheck className="w-3 h-3 mr-1" />
              )}
              Mark all read
            </Button>
          )}
        </DropdownMenuLabel>

        <ScrollArea className="h-[28rem] max-h-[60vh]">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-12 text-slate-400 dark:text-slate-500">
              <Loader2 className="w-6 h-6 animate-spin mb-2" />
              <p className="text-sm">Loading...</p>
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-slate-400 dark:text-slate-500">
              <BellOff className="w-10 h-10 mb-3 opacity-20" />
              <p className="text-sm font-medium">All caught up!</p>
              <p className="text-xs mt-0.5">No notifications to show.</p>
            </div>
          ) : (
            <div className="flex flex-col">
              {Object.entries(groups).map(([date, items], groupIdx) => (
                <div key={date}>
                  {groupIdx > 0 && <DropdownMenuSeparator className="bg-slate-100 dark:bg-slate-800 m-0" />}
                  <div className="px-3 py-1.5 bg-slate-50/50 dark:bg-black/10 border-y border-slate-100 dark:border-slate-800/60 first:border-t-0 sticky top-0 z-10 backdrop-blur-md">
                    <p className="text-slate-500 dark:text-slate-400 text-[10px] font-bold uppercase tracking-wider">
                      {date}
                    </p>
                  </div>
                  <div className="divide-y divide-slate-50 dark:divide-slate-800/30">
                    {items.map((n) => (
                      <DropdownMenuLabel
                        key={n.id}
                        asChild
                        className="p-0 font-normal"
                      >
                        <div
                          onClick={() => handleNotificationClick(n)}
                          className={cn(
                            "flex items-start gap-3 p-3 transition-colors cursor-pointer group",
                            n.is_read
                              ? "hover:bg-slate-50 dark:hover:bg-slate-800/50"
                              : "bg-orange-50/50 dark:bg-orange-500/10 hover:bg-orange-100/50 dark:hover:bg-orange-500/20"
                          )}
                        >
                          <NotifIcon type={n.notification_type} />
                          <div className="flex-1 min-w-0">
                            <p
                              className={cn(
                                "text-sm font-medium leading-tight",
                                n.is_read ? "text-slate-600 dark:text-slate-300" : "text-slate-900 dark:text-white"
                              )}
                            >
                              {n.title}
                            </p>
                            <p className="text-slate-500 dark:text-slate-400 text-xs mt-1 line-clamp-2 leading-relaxed">
                              {n.body}
                            </p>
                            <div className="flex items-center justify-between mt-2">
                              <time className="text-slate-400 dark:text-slate-500 text-[10px] font-medium">
                                {formatDistanceToNow(parseISO(n.created_at), { addSuffix: true })}
                              </time>
                              {!n.is_read && (
                                <div className="w-1.5 h-1.5 rounded-full bg-orange-500 shrink-0" />
                              )}
                            </div>
                          </div>
                        </div>
                      </DropdownMenuLabel>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
        <div className="p-2 border-t border-slate-100 dark:border-slate-800">
          <Button 
            variant="ghost" 
            className="w-full text-xs h-8 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
            onClick={() => navigate("/notifications")}
          >
            View all notifications
          </Button>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
