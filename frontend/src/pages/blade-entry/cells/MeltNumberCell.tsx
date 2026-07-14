import { Camera, Keyboard } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/utils/cn";
import type { GridRowState } from "@/store/bladeEntryStore";

export default function MeltNumberCell({
  row,
  rowIndex,
  isFocused,
  registerRef,
  onChange,
  onKeyDown,
  onFocus,
  onScanClick,
  onKeyboardClick,
}: {
  row: GridRowState;
  rowIndex: number;
  isFocused: boolean;
  registerRef: (el: HTMLInputElement | null) => void;
  onChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  onFocus: () => void;
  onScanClick: () => void;
  onKeyboardClick: () => void;
}) {
  const disabled = row.locked;
  return (
    <div className="relative">
      <Input
        ref={registerRef}
        value={row.melt_number}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={onFocus}
        readOnly={disabled}
        placeholder={disabled ? "" : "Scan or type…"}
        className={cn(
          "h-9 text-sm pr-14",
          disabled && "bg-slate-100 dark:bg-slate-800/60 text-slate-500 cursor-text",
          isFocused && "ring-2 ring-orange-400 border-orange-400",
          row.status === "error" && "border-red-400"
        )}
        data-row={rowIndex}
        data-col="melt_number"
      />
      <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
        <button
          type="button"
          onClick={onScanClick}
          title="Scan Melt Number via camera"
          className="p-1 rounded text-slate-400 hover:text-orange-500 hover:bg-orange-50 dark:hover:bg-orange-500/10 transition-colors"
        >
          <Camera className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={onKeyboardClick}
          title="Open Russian keyboard"
          className="p-1 rounded text-slate-400 hover:text-orange-500 hover:bg-orange-50 dark:hover:bg-orange-500/10 transition-colors"
        >
          <Keyboard className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
