import { Scale } from "lucide-react";
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
}: {
  row: GridRowState;
  rowIndex: number;
  isFocused: boolean;
  liveFromScale: boolean;
  registerRef: (el: HTMLInputElement | null) => void;
  onChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  onFocus: () => void;
}) {
  const disabled = row.locked;
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
          "h-9 text-sm pr-7",
          disabled && "bg-slate-100 dark:bg-slate-800/60 text-slate-500",
          isFocused && "ring-2 ring-orange-400 border-orange-400",
          liveFromScale && !disabled && "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/10"
        )}
        data-row={rowIndex}
        data-col="weight"
      />
      {liveFromScale && !disabled && (
        <Scale className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-emerald-500 pointer-events-none" />
      )}
    </div>
  );
}
