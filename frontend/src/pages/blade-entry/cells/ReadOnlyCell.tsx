import { cn } from "@/utils/cn";

export default function ReadOnlyCell({
  value,
  className,
}: {
  value: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "h-9 flex items-center px-2 text-sm text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 rounded-md select-none",
        className
      )}
    >
      {value}
    </div>
  );
}
