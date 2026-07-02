import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  BellOff,
  CheckCheck,
  ChevronRight,
  Loader2,
  Activity,
  Package,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
} from "lucide-react";
import { formatDistanceToNow, parseISO, format, isToday, isYesterday } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

import { notificationService } from "@/services/notificationService";
import { useNotificationStore } from "@/store/notificationStore";
import type { Notification, NotificationType } from "@/types";
import { cn } from "@/utils/cn";

// ─── Notification icon ────────────────────────────────────────────────────────

function NotifIcon({ type }: { type: NotificationType }) {
  const cfg: Record<
    NotificationType,
    { icon: React.ReactNode; bg: string; color: string }
  > = {
    // Backend types
    BLADE_RECEIVED: {
      icon: <Activity className="w-4 h-4" />,
      bg: "bg-indigo-500",
      color: "text-white",
    },
    SLOT_PENDING: {
      icon: <Package className="w-4 h-4" />,
      bg: "bg-violet-500",
      color: "text-white",
    },
    BALANCING_DONE: {
      icon: <CheckCircle2 className="w-4 h-4" />,
      bg: "bg-emerald-500",
      color: "text-white",
    },
    BLADE_REJECTED: {
      icon: <XCircle className="w-4 h-4" />,
      bg: "bg-red-500",
      color: "text-white",
    },
    VERIFICATION_PENDING: {
      icon: <ChevronRight className="w-4 h-4" />,
      bg: "bg-blue-500",
      color: "text-white",
    },
    SYSTEM: {
      icon: <Info className="w-4 h-4" />,
      bg: "bg-slate-500",
      color: "text-white",
    },
    // Legacy page aliases — map to closest backend equivalent
    BLADE_CREATED: {
      icon: <Activity className="w-4 h-4" />,
      bg: "bg-indigo-500",
      color: "text-white",
    },
    STATUS_CHANGED: {
      icon: <ChevronRight className="w-4 h-4" />,
      bg: "bg-blue-500",
      color: "text-white",
    },
    MEASUREMENT_ADDED: {
      icon: <Info className="w-4 h-4" />,
      bg: "bg-cyan-500",
      color: "text-white",
    },
    SLOT_ASSIGNED: {
      icon: <Package className="w-4 h-4" />,
      bg: "bg-violet-500",
      color: "text-white",
    },
    BALANCING_COMPLETE: {
      icon: <CheckCircle2 className="w-4 h-4" />,
      bg: "bg-emerald-500",
      color: "text-white",
    },
    REJECTION: {
      icon: <XCircle className="w-4 h-4" />,
      bg: "bg-red-500",
      color: "text-white",
    },
    HOLD: {
      icon: <AlertTriangle className="w-4 h-4" />,
      bg: "bg-amber-500",
      color: "text-white",
    },
    WORKFLOW_UPDATED: {
      icon: <ChevronRight className="w-4 h-4" />,
      bg: "bg-blue-500",
      color: "text-white",
    },
    GENERAL: {
      icon: <Info className="w-4 h-4" />,
      bg: "bg-slate-500",
      color: "text-white",
    },
  };
  const c = cfg[type] ?? cfg["SYSTEM"];
  return (
    <div className={cn("w-9 h-9 rounded-full flex items-center justify-center shrink-0", c.bg, c.color)}>
      {c.icon}
    </div>
  );
}

// ─── Group notifications by date ──────────────────────────────────────────────

function groupByDate(notifications: Notification[]) {
  const groups: Record<string, Notification[]> = {};
  for (const n of notifications) {
    const d = parseISO(n.created_at);
    const key = isToday(d) ? "Today" : isYesterday(d) ? "Yesterday" : format(d, "MMMM d, yyyy");
    if (!groups[key]) groups[key] = [];
    groups[key].push(n);
  }
  return groups;
}

// ─── Notification item ────────────────────────────────────────────────────────

function NotificationItem({
  notification,
  onRead,
}: {
  notification: Notification;
  onRead: (id: string) => void;
}) {
  const navigate = useNavigate();

  const handleClick = () => {
    if (!notification.is_read) onRead(notification.id);
    if (notification.blade_id) navigate(`/blades/${notification.blade_id}`);
  };

  return (
    <div
      onClick={handleClick}
      className={cn(
        "flex items-start gap-4 px-5 py-4 transition-colors cursor-pointer",
        notification.is_read
          ? "hover:bg-slate-50 dark:hover:bg-slate-700/20"
          : "bg-orange-50 dark:bg-slate-700/30 hover:bg-orange-100/60 dark:hover:bg-slate-700/50 border-l-2 border-orange-500"
      )}
    >
      <NotifIcon type={notification.notification_type} />

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p
            className={cn(
              "text-sm font-medium",
              notification.is_read ? "text-slate-600 dark:text-slate-300" : "text-slate-900 dark:text-white"
            )}
          >
            {notification.title}
          </p>
          <time className="text-slate-400 dark:text-slate-500 text-xs whitespace-nowrap shrink-0">
            {formatDistanceToNow(parseISO(notification.created_at), { addSuffix: true })}
          </time>
        </div>
        <p className="text-slate-500 dark:text-slate-400 text-sm mt-0.5 line-clamp-2">{notification.body}</p>
        {notification.blade_id && (
          <p className="text-orange-500 dark:text-orange-400 text-xs mt-1 font-mono">
            Blade: {notification.blade_id}
          </p>
        )}
      </div>

      {!notification.is_read && (
        <div className="w-2.5 h-2.5 rounded-full bg-orange-500 shrink-0 mt-1.5" />
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function NotificationsPage() {
  const queryClient = useQueryClient();
  const setNotifications = useNotificationStore((s) => s.setNotifications);
  const storeMarkAsRead = useNotificationStore((s) => s.markAsRead);
  const storeMarkAllRead = useNotificationStore((s) => s.markAllAsRead);
  const unreadCount = useNotificationStore((s) => s.unreadCount);

  const { data: notifications = [], isLoading } = useQuery<Notification[]>({
    queryKey: ["notifications"],
    queryFn: async () => {
      const data = await notificationService.list();
      setNotifications(data);
      return data;
    },
    staleTime: 0,           // always fetch fresh when page opens
    refetchInterval: 15_000, // poll every 15s while on this page
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

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">
      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm">
        <div className="flex items-center justify-between max-w-2xl mx-auto">
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Bell className="w-5 h-5 text-orange-500" />
              Notifications
              {unreadCount > 0 && (
                <span className="ml-1 rounded-full bg-orange-500 text-white text-xs px-2 py-0.5 font-semibold tabular-nums">
                  {unreadCount}
                </span>
              )}
            </h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">{notifications.length} total</p>
          </div>
          {unreadCount > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => markAllReadMutation.mutate()}
              disabled={markAllReadMutation.isPending}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              {markAllReadMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCheck className="w-4 h-4" />
              )}
              Mark All Read
            </Button>
          )}
        </div>
      </div>

      <div className="max-w-2xl mx-auto py-6 px-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-slate-400 dark:text-slate-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            Loading notifications…
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500">
            <BellOff className="w-16 h-16 mb-4 opacity-20" />
            <p className="text-lg font-medium">All caught up!</p>
            <p className="text-sm mt-1">No notifications to show</p>
          </div>
        ) : (
          <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
            <CardContent className="p-0">
              {Object.entries(groups).map(([date, items], groupIdx) => (
                <div key={date}>
                  {groupIdx > 0 && <Separator className="bg-slate-200 dark:bg-slate-700/50" />}
                  {/* Date header */}
                  <div className="px-5 py-2.5 bg-slate-50 dark:bg-slate-800/40">
                    <p className="text-slate-500 dark:text-slate-400 text-xs font-semibold uppercase tracking-wider">
                      {date}
                    </p>
                  </div>
                  {/* Items */}
                  <div className="divide-y divide-slate-100 dark:divide-slate-700/30">
                    {items.map((n) => (
                      <NotificationItem
                        key={n.id}
                        notification={n}
                        onRead={(id) => markReadMutation.mutate(id)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
