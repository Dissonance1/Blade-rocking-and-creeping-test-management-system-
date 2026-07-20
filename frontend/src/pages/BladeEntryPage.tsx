import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { BladeEntryIcon } from "@/components/common/CustomIcons";
import { workOrderService } from "@/services/workOrderService";
import { useBladeEntryStore } from "@/store/bladeEntryStore";
import WorkOrderCommonInfoForm from "./blade-entry/WorkOrderCommonInfoForm";
import BladeEntryGrid from "./blade-entry/BladeEntryGrid";

export default function BladeEntryPage() {
  const navigate = useNavigate();
  const { workOrderNumber } = useParams<{ workOrderNumber?: string }>();
  const { phase, loadFromServer, reset } = useBladeEntryStore();

  // Guards against re-hydrating the grid from a stale server snapshot after
  // the operator has already started typing — see hasLoadedRef usage below.
  const hasLoadedRef = useRef(false);

  // Reset store state whenever the target Work Order changes (or on unmount) —
  // a shared shop-floor PC must never leak a previous session's half-typed row.
  useEffect(() => {
    hasLoadedRef.current = false;
    reset();
    return () => reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workOrderNumber]);

  const { data, isLoading } = useQuery({
    queryKey: ["work-order-entry", workOrderNumber],
    queryFn: () => workOrderService.getEntry(workOrderNumber!),
    enabled: !!workOrderNumber,
    // This screen is single-writer, autosave-driven — a background poll or
    // window-focus refetch landing mid-entry would otherwise clobber whatever
    // the operator is actively typing (rows are hydrated wholesale below).
    refetchInterval: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });

  useEffect(() => {
    // Only hydrate the grid from the server once per Work Order. Once typed,
    // local row state is the source of truth until the page is left/reset;
    // re-running this on every refetch would overwrite in-progress edits.
    if (data && !hasLoadedRef.current) {
      hasLoadedRef.current = true;
      loadFromServer(data);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const handleStarted = (wo: string) => {
    navigate(`/blades/${encodeURIComponent(wo)}/entry`, { replace: true });
  };

  const showLoading = !!workOrderNumber && isLoading;

  return (
    <div className="h-full flex flex-col overflow-hidden bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5 shadow-sm">
        <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
          <BladeEntryIcon className="w-5 h-5 text-orange-500 shrink-0" />
          Blade Entry
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          OH Station — Work Order grid entry (90 blades)
        </p>
      </div>

      <div className="flex-1 min-h-0 w-full px-4 sm:px-6 pt-4 pb-4 flex flex-col overflow-hidden">
        {showLoading ? (
          <div className="flex-1 flex items-center justify-center text-slate-400">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            Loading Work Order…
          </div>
        ) : phase === "grid" ? (
          <BladeEntryGrid />
        ) : (
          <WorkOrderCommonInfoForm onStarted={handleStarted} />
        )}
      </div>
    </div>
  );
}
