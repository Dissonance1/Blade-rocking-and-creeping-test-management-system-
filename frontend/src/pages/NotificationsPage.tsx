import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import {
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
import { BellIcon } from "@/components/common/CustomIcons";
import { formatDistanceToNow, parseISO, format, isToday, isYesterday } from "date-fns";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

import { notificationService } from "@/services/notificationService";
import { useNotificationStore } from "@/store/notificationStore";
import type { Notification, NotificationType, PaginatedResponse } from "@/types";
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
    SYSTEM_ALERT: {
      icon: <AlertTriangle className="w-4 h-4" />,
      bg: "bg-red-500",
      color: "text-white",
    },
    BLADE_READY_FOR_ASSEMBLY: {
      icon: <ChevronRight className="w-4 h-4" />,
      bg: "bg-blue-500",
      color: "text-white",
    },
    ASSEMBLY_RECEIVED: {
      icon: <CheckCircle2 className="w-4 h-4" />,
      bg: "bg-indigo-500",
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
        "flex items-start gap-3 sm:gap-4 px-4 sm:px-5 py-4 transition-colors cursor-pointer",
        notification.is_read
          ? "hover:bg-slate-50 dark:hover:bg-slate-800/50"
          : "bg-orange-50 dark:bg-background hover:bg-orange-100/60 dark:hover:bg-slate-800/60 border-l-2 border-orange-500"
      )}
    >
      <NotifIcon type={notification.notification_type} />

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p
            className={cn(
              "text-sm font-medium min-w-0",
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
          <p className="text-orange-500 dark:text-orange-400 text-xs mt-1 font-mono truncate">
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

const PAGE_SIZE = 20;
const NOTIF_QUERY_KEY = ["notifications", "unread-feed"] as const;
type NotifPage = PaginatedResponse<Notification>;

export default function NotificationsPage() {
  const queryClient = useQueryClient();
  const setNotifications = useNotificationStore((s) => s.setNotifications);
  const storeMarkAsRead = useNotificationStore((s) => s.markAsRead);
  const storeMarkAllRead = useNotificationStore((s) => s.markAllAsRead);
  const unreadCount = useNotificationStore((s) => s.unreadCount);

  // Only unread notifications are shown — once read, an item is gone for
  // good rather than sticking around greyed out. Pages are fetched with a
  // fixed page size and a growing `skip` (real cursor pagination) rather
  // than re-requesting everything with an ever-growing `limit` — the
  // backend caps `limit` at 100, so that approach silently broke once more
  // than 100 notifications existed and could never reach the rest.
  const {
    data,
    isLoading,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery({
    queryKey: NOTIF_QUERY_KEY,
    queryFn: ({ pageParam }) =>
      notificationService.listPaginated({ unread_only: true, skip: pageParam, limit: PAGE_SIZE }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
    staleTime: 0,           // always fetch fresh when page opens
    refetchInterval: 15_000, // poll every 15s while on this page
  });

  const notifications = data?.pages.flatMap((p) => p.items) ?? [];

  useEffect(() => {
    setNotifications(notifications);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const markReadMutation = useMutation({
    mutationFn: (id: string) => notificationService.markRead(id),
    onSuccess: (_, id) => {
      storeMarkAsRead(id);
      queryClient.setQueryData(NOTIF_QUERY_KEY, (old: InfiniteData<NotifPage, number> | undefined) =>
        old
          ? {
              ...old,
              pages: old.pages.map((p) => ({
                ...p,
                items: p.items.filter((n) => n.id !== id),
                total: Math.max(0, p.total - 1),
              })),
            }
          : old
      );
      queryClient.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: notificationService.markAllRead,
    onSuccess: () => {
      storeMarkAllRead();
      queryClient.setQueryData(NOTIF_QUERY_KEY, (old: InfiniteData<NotifPage, number> | undefined) =>
        old && old.pages[0]
          ? { pages: [{ ...old.pages[0], items: [], total: 0 }], pageParams: [0] }
          : old
      );
      queryClient.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
    },
  });

  const groups = groupByDate(notifications);

  // `isFetchingNextPage` flips on every 15s poll refetch too, not just on a
  // "load more" — read it via a ref inside the observer callback instead of
  // depending on it directly, so the observer isn't torn down and
  // recreated on every poll (which was re-triggering itself while still
  // intersecting and spamming "load more" in a loop).
  const isFetchingRef = useRef(isFetchingNextPage);
  useEffect(() => {
    isFetchingRef.current = isFetchingNextPage;
  }, [isFetchingNextPage]);

  // Infinite scroll — fetch the next page automatically once the sentinel
  // below the list scrolls into view. This page scrolls as part of the
  // normal page flow (not a fixed-height internal container), and
  // IntersectionObserver still fires correctly regardless of which ancestor
  // is the actual scrolling element.
  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasNextPage) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isFetchingRef.current) {
          fetchNextPage();
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, fetchNextPage]);

  return (
    <div className="w-full max-w-[1600px] mx-auto text-slate-900 dark:text-white">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2">
            <BellIcon className="w-5 h-5 text-orange-500 shrink-0" />
            Notifications
            {unreadCount > 0 && (
              <span className="ml-1 rounded-full bg-orange-500 text-white text-xs px-2 py-0.5 font-semibold tabular-nums">
                {unreadCount}
              </span>
            )}
          </h1>
        </div>
        {unreadCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => markAllReadMutation.mutate()}
            disabled={markAllReadMutation.isPending}
            className="w-full sm:w-auto border-2 border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            {markAllReadMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <CheckCheck className="w-4 h-4 mr-1.5" />
            )}
            Mark All Read
          </Button>
        )}
      </div>

      {/* Content */}
      <div>
        <div className="bg-white/70 dark:bg-background backdrop-blur-xl rounded-2xl border border-white/60 dark:border-white/10 shadow-xl shadow-slate-200/50 dark:shadow-black/20 overflow-hidden">
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
            <div>
              {Object.entries(groups).map(([date, items], groupIdx) => (
                <div key={date}>
                  {groupIdx > 0 && <Separator className="bg-slate-100 dark:bg-slate-800/50 m-0" />}
                  {/* Date header */}
                  <div className="px-4 sm:px-5 py-2 bg-slate-100/50 dark:bg-background border-b border-slate-100 dark:border-slate-800/60 sticky top-0 z-10 backdrop-blur-md">
                    <p className="text-slate-500 dark:text-slate-400 text-xs font-bold uppercase tracking-wider">
                      {date}
                    </p>
                  </div>
                  {/* Items */}
                  <div className="divide-y divide-slate-100/50 dark:divide-slate-800/30">
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
            </div>
          )}
        </div>

        {hasNextPage && (
          <div ref={sentinelRef} className="flex justify-center py-4 text-slate-400 dark:text-slate-500">
            {isFetchingNextPage && (
              <span className="flex items-center gap-1.5 text-xs">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading more…
              </span>
            )}
          </div>
        )}
      </div>

    </div>
  );
}
