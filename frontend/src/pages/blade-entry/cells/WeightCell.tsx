import { Scale, Lock, Unlock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/utils/cn";
import type { GridRowState } from "@/store/bladeEntryStore";

export default function WeightCell({
  row,
  rowIndex,
  isFocused,
  liveFromScale,
  registerRef,
  onChange,
  onKeyDown,
  onFocus,
  onLockWeight,
  onUnlockWeight,
}: {
  row: GridRowState;
  rowIndex: number;
  isFocused: boolean;
  liveFromScale: boolean;
  registerRef: (el: HTMLInputElement | null) => void;
  onChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  onFocus: () => void;
  onLockWeight: () => void;
  onUnlockWeight: () => void;
}) {
  const disabled = row.locked;
  const canLock = !disabled && row.raw_weight.trim().length > 0;
  return (
    <div className="relative">
      <Input
        ref={registerRef}
        type="number"
        step="0.01"
        min={0}
        value={row.raw_weight}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={onFocus}
        readOnly={disabled}
        placeholder={disabled ? "" : "0.00"}
        className={cn(
          "h-9 text-sm pr-14",
          disabled && "bg-slate-100 dark:bg-slate-800/60 text-slate-500",
          isFocused && "ring-2 ring-orange-400 border-orange-400",
          liveFromScale && !disabled && "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/10"
        )}
        data-row={rowIndex}
        data-col="weight"
      />
      <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
        {liveFromScale && !disabled && <Scale className="w-3.5 h-3.5 text-emerald-500 pointer-events-none" />}
        {disabled ? (
          <button
            type="button"
            onClick={onUnlockWeight}
            title="Unlock to edit this row"
            className="p-1 rounded text-slate-400 hover:text-orange-500 hover:bg-orange-50 dark:hover:bg-orange-500/10 transition-colors"
          >
            <Lock className="w-3.5 h-3.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onLockWeight}
            disabled={!canLock}
            title={canLock ? "Lock weight and move to next row" : "Enter a weight to lock"}
            className="p-1 rounded text-slate-400 hover:text-orange-500 hover:bg-orange-50 dark:hover:bg-orange-500/10 transition-colors disabled:opacity-30 disabled:hover:text-slate-400 disabled:hover:bg-transparent"
          >
            <Unlock className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
