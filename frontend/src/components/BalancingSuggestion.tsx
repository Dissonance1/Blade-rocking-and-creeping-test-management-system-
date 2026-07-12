import { useState, useMemo } from "react";
import { Calculator, Scale, Package, Loader2, CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BladeListItem, SlotAllocation } from "@/types";
import { cn } from "@/utils/cn";

interface BalancingSuggestionProps {
  blades: BladeListItem[];
  slots?: SlotAllocation[];
  onAssign?: (imbalanceSlot: number, totalSlots: number) => void;
  isAssigning?: boolean;
}

export function BalancingSuggestion({ blades, slots = [], onAssign, isAssigning }: BalancingSuggestionProps) {
  const [imbalanceSlot, setImbalanceSlot] = useState("");
  const [totalSlots, setTotalSlots] = useState("90");

  // blade_id → actual assigned slot_number (active allocations only)
  const assignedSlotMap = useMemo(() => {
    const map: Record<string, string> = {};
    slots.filter((s) => s.is_active).forEach((s) => { map[s.blade_id] = s.slot_number; });
    return map;
  }, [slots]);

  const anyAssigned = blades.some((b) => assignedSlotMap[b.id] !== undefined);
  const allAssigned = blades.length > 0 && blades.every((b) => assignedSlotMap[b.id] !== undefined);

  const N = Math.max(1, parseInt(totalSlots, 10) || 90);
  const K = parseInt(imbalanceSlot, 10);
  const valid = K >= 1 && K <= N;

  const sorted = useMemo(
    () => [...blades].sort((a, b) => (b.static_moment_gcm ?? 0) - (a.static_moment_gcm ?? 0)),
    [blades]
  );

  // Interleave: first half (heavy) + reversed second half (light)
  // So each heavy blade ends up opposite a light blade on the disc.
  const interleaved = useMemo(() => {
    const half = Math.floor(sorted.length / 2);
    return [...sorted.slice(0, half), ...[...sorted.slice(half)].reverse()];
  }, [sorted]);

  const assignments = useMemo(() =>
    interleaved.map((b, i) => ({
      blade: b,
      // Original SM rank (1 = heaviest) for display
      rank: sorted.indexOf(b) + 1,
      slot: valid ? ((K - 1 + i) % N) + 1 : null as number | null,
    })),
    [interleaved, sorted, valid, K, N]
  );

  const { cwSlot, cwValue } = useMemo(() => {
    if (!valid || assignments.length === 0) return { cwSlot: null, cwValue: null };
    let sx = 0, sy = 0;
    assignments.forEach(({ blade, slot }) => {
      if (slot == null) return;
      const a = ((slot - 1) / N) * 2 * Math.PI;
      const sm = blade.static_moment_gcm ?? 0;
      sx += sm * Math.cos(a);
      sy += sm * Math.sin(a);
    });
    const mag = Math.sqrt(sx * sx + sy * sy);
    const ang = Math.atan2(-sy, -sx);
    const raw = (ang / (2 * Math.PI)) * N;
    const cw = ((Math.round(raw) % N) + N) % N + 1;
    return { cwSlot: cw, cwValue: mag };
  }, [assignments, valid, N]);

  if (blades.length === 0) return null;

  return (
    <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
          <Calculator className="w-4 h-4 text-orange-500" />
          Slot Assignment &amp; Balancing Suggestion
          <span className="text-xs font-normal text-slate-400 dark:text-slate-500">
            — Enter imbalance slot no. from equipment reading
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Inputs row */}
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1">
            <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">
              Imbalance Slot No. <span className="text-red-500">*</span>
            </Label>
            <Input
              type="number"
              min={1}
              max={N}
              value={imbalanceSlot}
              onChange={(e) => setImbalanceSlot(e.target.value)}
              placeholder="e.g. 12"
              className="w-32 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-slate-600 dark:text-slate-300 text-xs font-medium">
              Total Slots in Disk
            </Label>
            <Input
              type="number"
              min={1}
              value={totalSlots}
              onChange={(e) => setTotalSlots(e.target.value)}
              className="w-28 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
            />
          </div>
          {cwSlot && (
            <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/50 px-4 py-2.5 flex items-center gap-3">
              <Scale className="w-4 h-4 text-amber-600 dark:text-amber-400" />
              <div>
                <p className="text-xs text-amber-600 dark:text-amber-400 font-semibold">
                  Counter Weight → Slot {cwSlot}
                </p>
                <p className="text-xs font-mono text-amber-700 dark:text-amber-300">
                  ≈ {cwValue?.toFixed(1)} g·cm (opposite side)
                </p>
              </div>
            </div>
          )}
          {!valid && blades.length > 0 && (
            <p className="text-xs text-slate-400 dark:text-slate-500 italic">
              {blades.length} blade{blades.length !== 1 ? "s" : ""} ready — enter imbalance slot to see suggested placement
            </p>
          )}
          {valid && onAssign && !allAssigned && (
            <Button
              size="sm"
              className="bg-cyan-600 hover:bg-cyan-500 text-white"
              onClick={() => onAssign(K, N)}
              disabled={isAssigning}
            >
              {isAssigning ? (
                <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
              ) : (
                <Package className="w-4 h-4 mr-1.5" />
              )}
              Assign Slots to All Blades
            </Button>
          )}
        </div>

        {/* Suggestion table — 45 / 45 split */}
        {(() => {
          const COLS = ["#", "Serial No.", "Wt (g)", "SM (g·cm)", anyAssigned ? "Assigned Slot" : "Slot"];
          const half = Math.ceil(assignments.length / 2);
          const leftRows  = assignments.slice(0, half);
          const rightRows = assignments.slice(half);

          const renderHalf = (rows: typeof assignments, offset: number) => (
            <table className="w-full text-xs whitespace-nowrap">
              <thead className="bg-slate-100 dark:bg-background sticky top-0 z-10">
                <tr>
                  {COLS.map((h) => (
                    <th key={h} className="px-2 py-2 text-slate-600 dark:text-slate-300 font-semibold uppercase tracking-wide text-left whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700/30">
                {rows.map(({ blade, rank, slot }, idx) => (
                  <tr
                    key={blade.id}
                    className={cn(
                      idx % 2 === 0 ? "bg-white dark:bg-transparent" : "bg-slate-50/60 dark:bg-background",
                      valid && slot === K && "bg-orange-50 dark:bg-orange-900/10"
                    )}
                  >
                    <td className="px-2 py-1.5">
                      <span className={cn(
                        "inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold",
                        rank === 1
                          ? "bg-orange-500 text-white"
                          : "bg-slate-200 dark:bg-background text-slate-700 dark:text-slate-200"
                      )}>
                        {offset + idx + 1}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-orange-500 dark:text-orange-400 font-medium whitespace-nowrap">
                      {blade.serial_number}
                    </td>
                    <td className="px-2 py-1.5 font-mono tabular-nums text-slate-700 dark:text-slate-200 font-medium">
                      {blade.weight_grams != null ? blade.weight_grams.toFixed(2) : "—"}
                    </td>
                    <td className="px-2 py-1.5 font-mono tabular-nums text-slate-700 dark:text-slate-200 font-medium">
                      {blade.static_moment_gcm != null ? blade.static_moment_gcm.toFixed(2) : "—"}
                    </td>
                    <td className="px-2 py-1.5">
                      {(() => {
                        const actual = assignedSlotMap[blade.id];
                        if (actual) {
                          return (
                            <span className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-xs font-semibold bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 whitespace-nowrap">
                              <CheckCircle2 className="w-3 h-3" />
                              {actual}
                            </span>
                          );
                        }
                        if (slot != null) {
                          return (
                            <span className={cn(
                              "inline-flex items-center rounded-full px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap",
                              slot === K
                                ? "bg-orange-500 text-white"
                                : "bg-slate-100 dark:bg-background text-slate-700 dark:text-slate-200"
                            )}>
                              {slot}
                            </span>
                          );
                        }
                        return <span className="text-slate-400 text-xs">—</span>;
                      })()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          );

          return (
            <div className="rounded-lg border border-slate-200 dark:border-slate-700/50 overflow-hidden">
              <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-slate-200 dark:divide-slate-700">
                <div className="overflow-x-auto">{renderHalf(leftRows, 0)}</div>
                <div className="overflow-x-auto">{renderHalf(rightRows, half)}</div>
              </div>
              {cwSlot && (
                <div className="border-t-2 border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/10 px-4 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold bg-amber-500 text-white flex-shrink-0">CW</span>
                  <span className="font-semibold text-amber-700 dark:text-amber-400">Counter Weight</span>
                  <span className="font-mono text-amber-700 dark:text-amber-300 tabular-nums">{cwValue?.toFixed(1)} g·cm</span>
                  <span className="inline-flex items-center rounded-full px-2 py-0.5 font-semibold bg-amber-500 text-white">Slot {cwSlot}</span>
                </div>
              )}
            </div>
          );
        })()}
      </CardContent>
    </Card>
  );
}
