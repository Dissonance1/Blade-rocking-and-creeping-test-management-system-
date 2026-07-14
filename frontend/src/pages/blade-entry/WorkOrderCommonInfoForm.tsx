import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Loader2,
  AlertCircle,
  ClipboardList,
  Check,
  Search,
  ArrowRight,
  Inbox,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/utils/cn";
import { extractApiError } from "@/services/api";
import { workOrderService } from "@/services/workOrderService";
import { batchService } from "@/services/batchService";
import { useBladeEntryStore } from "@/store/bladeEntryStore";

const hhmmssRegex = /^\d{1,5}:[0-5]\d:[0-5]\d$/;
const hoursField = z.string().regex(hhmmssRegex, "Format must be HH:MM:SS (e.g. 1500:30:00)");

const schema = z.object({
  work_order_number: z.string().min(1, "Work Order Number is required"),
  shop_order_number: z.string().min(1, "Shop Order Number is required"),
  part_number: z.string().min(1, "Part Number is required"),
  blade_type: z.enum(["LPTR", "HPTR"]),
  engine_number: z.string().optional(),
  engine_hours: hoursField,
  component_hours: z
    .string()
    .optional()
    .refine((v) => !v || hhmmssRegex.test(v), { message: "Format must be HH:MM:SS (e.g. 1500:30:00)" }),
});

type FormValues = z.infer<typeof schema>;

function FieldRow({
  label,
  children,
  error,
  required,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  error?: string | undefined;
  required?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </Label>
      {children}
      {error && <p className="text-red-500 dark:text-red-400 text-xs">{error}</p>}
    </div>
  );
}

// ─── Resume panel — lists Work Orders whose Blade Entry isn't complete ───────

function ResumeWorkOrderPanel() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");

  const { data: batches = [], isLoading } = useQuery({
    queryKey: ["batches"],
    queryFn: () => batchService.list(),
    refetchInterval: 30_000,
  });

  const incomplete = useMemo(() => {
    const q = search.trim().toLowerCase();
    return batches
      .filter((b) => !b.is_entry_complete)
      .filter(
        (b) =>
          !q ||
          b.work_order_number.toLowerCase().includes(q) ||
          (b.part_number ?? "").toLowerCase().includes(q) ||
          (b.engine_number ?? "").toLowerCase().includes(q)
      )
      .sort((a, b) => (b.first_blade_at ?? "").localeCompare(a.first_blade_at ?? ""));
  }, [batches, search]);

  return (
    <div className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-2xl shadow-sm flex flex-col h-full">
      <div className="px-5 pt-5 pb-3 border-b border-slate-100 dark:border-slate-700/60">
        <h2 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
          <Wrench className="w-4 h-4 text-orange-500" />
          Resume Blade Entry
        </h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          Work Orders still missing rows — pick up where you left off.
        </p>
        <div className="relative mt-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search Work Order, part, engine…"
            className="h-10 pl-9 text-sm bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto max-h-[28rem] divide-y divide-slate-100 dark:divide-slate-700/60">
        {isLoading && (
          <div className="p-6 flex items-center justify-center text-slate-400 text-sm gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        )}
        {!isLoading && incomplete.length === 0 && (
          <div className="p-6 flex flex-col items-center justify-center text-center text-slate-400 gap-2">
            <Inbox className="w-8 h-8" />
            <p className="text-sm">No incomplete Work Orders{search ? " match your search" : ""}.</p>
          </div>
        )}
        {incomplete.map((b) => (
          <button
            key={b.work_order_number}
            type="button"
            onClick={() => navigate(`/blades/${encodeURIComponent(b.work_order_number)}/entry`)}
            className="w-full text-left px-5 py-3 hover:bg-orange-50/60 dark:hover:bg-orange-500/5 transition-colors flex items-center justify-between gap-3 group"
          >
            <div className="min-w-0">
              <p className="font-mono text-sm font-semibold text-slate-900 dark:text-white truncate">
                {b.work_order_number}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                {b.part_number ?? "—"} · {b.blade_type ?? "—"}
                {b.engine_number ? ` · ${b.engine_number}` : ""}
              </p>
            </div>
            <ArrowRight className="w-4 h-4 text-slate-300 group-hover:text-orange-500 shrink-0 transition-colors" />
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Main form ────────────────────────────────────────────────────────────────

export default function WorkOrderCommonInfoForm({ onStarted }: { onStarted: (workOrderNumber: string) => void }) {
  const [bladeType, setBladeType] = useState<"LPTR" | "HPTR">("LPTR");
  const loadFromServer = useBladeEntryStore((s) => s.loadFromServer);

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { blade_type: "LPTR" },
  });

  const startMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      return workOrderService.create({
        work_order_number: values.work_order_number.trim(),
        shop_order_number: values.shop_order_number.trim(),
        part_number: values.part_number.trim(),
        blade_type: bladeType,
        engine_number: values.engine_number?.trim() || null,
        engine_hours: values.engine_hours,
        component_hours: values.component_hours?.trim() || null,
      });
    },
    onSuccess: (detail) => {
      loadFromServer(detail);
      onStarted(detail.work_order_number);
    },
  });

  const inputCls =
    "h-11 text-sm bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400";

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-7xl mx-auto grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-6 items-start pb-6">
        {/* ── Start new Work Order ──────────────────────────────────────── */}
        <div className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-2xl shadow-sm">
          <div className="px-6 sm:px-8 pt-6 pb-4 border-b border-slate-100 dark:border-slate-700/60">
            <h2 className="text-xl font-semibold text-slate-900 dark:text-white flex items-center gap-2.5">
              <ClipboardList className="w-6 h-6 text-orange-500" />
              Start Blade Entry — Common Info
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Entered once for this set of 90 blades. These values are locked once entry starts.
            </p>
          </div>

          <div className="px-6 sm:px-8 py-6 space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-5">
              <FieldRow label="Work Order Number" error={errors.work_order_number?.message} required>
                <Input className={inputCls} {...register("work_order_number")} placeholder="WO-2024-0099" />
              </FieldRow>

              <FieldRow label="Shop Order Number" error={errors.shop_order_number?.message} required>
                <Input className={inputCls} {...register("shop_order_number")} placeholder="SO-0456" />
              </FieldRow>

              <FieldRow label="Part Number" error={errors.part_number?.message} required>
                <Input className={inputCls} {...register("part_number")} placeholder="PT-JT9D-1A" />
              </FieldRow>

              <FieldRow label="Engine Number" error={errors.engine_number?.message}>
                <Input
                  className={inputCls}
                  {...register("engine_number")}
                  placeholder="ENG-20240012 (append _1, _2…)"
                />
              </FieldRow>

              <FieldRow label="Engine Hours" error={errors.engine_hours?.message} required>
                <Input className={inputCls} {...register("engine_hours")} placeholder="HH:MM:SS" />
              </FieldRow>

              <FieldRow label="Component Hours" error={errors.component_hours?.message}>
                <Input
                  className={inputCls}
                  {...register("component_hours")}
                  placeholder="HH:MM:SS (blank = copy Engine Hours)"
                />
              </FieldRow>
            </div>

            <FieldRow label="Blade Type" required>
              <div className="grid grid-cols-2 sm:flex sm:w-80 gap-3">
                {(["LPTR", "HPTR"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => {
                      setBladeType(t);
                      setValue("blade_type", t);
                    }}
                    className={cn(
                      "flex-1 rounded-xl border-2 py-3 px-4 text-sm font-semibold transition-all",
                      bladeType === t
                        ? "border-orange-500 bg-orange-500 text-white shadow-md"
                        : "border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-background hover:border-orange-400"
                    )}
                  >
                    <span className="block text-base font-bold">{t}</span>
                    <span className="block text-xs font-normal mt-0.5 opacity-80">
                      {t === "LPTR" ? "Rocking + Creep" : "Rocking only"}
                    </span>
                  </button>
                ))}
              </div>
              <input type="hidden" {...register("blade_type")} value={bladeType} />
            </FieldRow>

            {startMutation.isError && (
              <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
                <AlertCircle className="h-4 w-4 text-red-500" />
                <AlertDescription className="text-red-700 dark:text-red-300">
                  {extractApiError(startMutation.error)}
                </AlertDescription>
              </Alert>
            )}

            <div className="flex justify-end pt-2 border-t border-slate-100 dark:border-slate-700/60">
              <Button
                type="button"
                onClick={handleSubmit((v) => startMutation.mutate(v))}
                disabled={startMutation.isPending}
                size="lg"
                className="bg-orange-500 hover:bg-orange-600 text-white px-10 mt-4"
              >
                {startMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Starting…
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4" />
                    Start Blade Entry
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>

        {/* ── Resume an in-progress Work Order ──────────────────────────── */}
        <ResumeWorkOrderPanel />
      </div>
    </div>
  );
}
