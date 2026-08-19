import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import { BladeEntryIcon } from "@/components/common/CustomIcons";
import { Button } from "@/components/ui/button";
import { workOrderService } from "@/services/workOrderService";
import { useBladeEntryStore } from "@/store/bladeEntryStore";
import WorkOrderCommonInfoForm from "./blade-entry/WorkOrderCommonInfoForm";
import BladeEntryGrid from "./blade-entry/BladeEntryGrid";

export default function BladeEntryPage() {
  const navigate = useNavigate();
  const { workOrderNumber } = useParams<{ workOrderNumber?: string }>();
  const { phase, loadFromServer, mergeFromServer, reset } = useBladeEntryStore();

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
    // refetchOnMount "always" forces one fresh fetch each time the page is
    // entered/re-entered, so a shared shop-floor PC never shows a stale
    // cached snapshot from a previous visit. The 5s poll on top of that
    // covers the case where a *second* browser/station has this same Work
    // Order open at once — its saved rows would otherwise only ever appear
    // after a manual reload. Polling is safe here because mergeFromServer
    // (below) only ever touches rows that are untouched locally, never the
    // row the operator is actively typing.
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    refetchOnMount: "always",
    staleTime: Infinity,
  });

  useEffect(() => {
    if (!data) return;
    if (!hasLoadedRef.current) {
      // First load for this Work Order: hydrate the whole grid.
      hasLoadedRef.current = true;
      loadFromServer(data);
    } else {
      // Subsequent poll: merge in rows saved elsewhere without touching
      // whatever the operator is actively typing here.
      mergeFromServer(data);
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
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate(-1)}
            className="shrink-0 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          >
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <BladeEntryIcon className="w-5 h-5 text-orange-500 shrink-0" />
              Blade Entry
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              OH Station — Work Order grid entry (90 blades)
            </p>
          </div>
        </div>
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
