import { useMemo, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronDown, Search } from "lucide-react";
import { cn } from "@/utils/cn";

export interface WorkOrderComboboxOption {
  value: string;
  label: string;
}

/** Single searchable dropdown for picking a work order — replaces a plain
 * <select> with a filter-as-you-type list, without the separate search box
 * stacked on top looking like two disconnected controls. */
export function WorkOrderCombobox({
  value,
  onChange,
  options,
  placeholder = "— Select a work order —",
  emptyMessage = "No work orders found.",
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  options: WorkOrderComboboxOption[];
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.label.toLowerCase().includes(q));
  }, [options, query]);

  const selected = options.find((o) => o.value === value);

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQuery("");
      }}
    >
      <Popover.Trigger asChild>
        <button
          type="button"
          className={cn(
            "w-full flex items-center justify-between gap-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-background text-slate-900 dark:text-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500",
            className
          )}
        >
          <span className={cn("truncate text-left", !selected && "text-slate-400")}>
            {selected ? selected.label : placeholder}
          </span>
          <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 w-[var(--radix-popover-trigger-width)] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-background shadow-lg overflow-hidden"
        >
          <div className="relative border-b border-slate-100 dark:border-slate-700/60">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search work order number…"
              className="w-full bg-transparent pl-9 pr-3 py-2.5 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none"
            />
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 && (
              <p className="px-3 py-2.5 text-xs text-slate-400">{emptyMessage}</p>
            )}
            {filtered.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                  setQuery("");
                }}
                className={cn(
                  "w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-orange-50 dark:hover:bg-orange-500/10",
                  o.value === value && "bg-orange-50 dark:bg-orange-500/10 font-medium text-orange-600 dark:text-orange-400"
                )}
              >
                <span className="truncate">{o.label}</span>
                {o.value === value && <Check className="w-4 h-4 shrink-0" />}
              </button>
            ))}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
