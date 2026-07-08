import { useState, useMemo } from "react";
import { Search, Pencil, Check, X, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from "@/components/ui/dialog";
import type { BladeListItem, BladeStatus } from "@/types";
import { cn } from "@/utils/cn";

// ─── Shared types ─────────────────────────────────────────────────────────────

export interface BladeModification {
  blade_id: string;
  serial_number: string;
  original: {
    weight_grams: number | null;
    static_moment_gcm: number | null;
    melt_number: string;
    part_number: string;
    nomenclature: string;
    work_order_number: string;
    shop_order_number: string;
    engine_number: string;
  };
  updated: {
    weight_grams: number | null;
    static_moment_gcm: number | null;
    melt_number: string;
    part_number: string;
    nomenclature: string;
    work_order_number: string;
    shop_order_number: string;
    engine_number: string;
  };
}

export interface ModifySubmitData {
  modifications: BladeModification[];
  remarks: string;
}

// ─── Field config ─────────────────────────────────────────────────────────────

type EditableFields = Omit<BladeModification["updated"], "weight_grams" | "static_moment_gcm"> & {
  weight_grams: string;
  static_moment_gcm: string;
};

const FIELD_LABELS: Record<string, string> = {
  weight_grams: "Weight (g)",
  static_moment_gcm: "Static Moment (g·cm)",
  melt_number: "Melt No.",
  part_number: "Part No.",
  nomenclature: "Nomenclature",
  work_order_number: "Work Order",
  shop_order_number: "Shop Order",
  engine_number: "Engine No.",
};

// ─── Blade status badge ───────────────────────────────────────────────────────

const BLADE_STATUS_CLS: Partial<Record<BladeStatus, string>> = {
  CREATED: "bg-slate-400 text-white",
  OH_INSPECTION: "bg-blue-400 text-white",
  MEASUREMENTS_RECORDED: "bg-sky-500 text-white",
  SENT_TO_ASSEMBLY: "bg-violet-500 text-white",
  SLOT_ASSIGNED: "bg-cyan-500 text-white",
  BALANCING_IN_PROGRESS: "bg-orange-500 text-white",
  BALANCING_COMPLETED: "bg-emerald-500 text-white",
  RETURNED_TO_OH: "bg-amber-500 text-white",
  REJECTED: "bg-red-500 text-white",
};

function BladeStatusBadge({ status }: { status: BladeStatus }) {
  const cls = BLADE_STATUS_CLS[status] ?? "bg-slate-500 text-white";
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap", cls)}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function bladeToOriginal(blade: BladeListItem): BladeModification["original"] {
  return {
    weight_grams: blade.weight_grams ?? null,
    static_moment_gcm: blade.static_moment_gcm ?? null,
    melt_number: blade.melt_number ?? "",
    part_number: blade.part_number ?? "",
    nomenclature: blade.nomenclature ?? "",
    work_order_number: blade.work_order_number ?? "",
    shop_order_number: blade.shop_order_number ?? "",
    engine_number: blade.engine_number ?? "",
  };
}

function emptyEditFields(blade: BladeListItem): EditableFields {
  return {
    weight_grams: blade.weight_grams != null ? String(blade.weight_grams) : "",
    static_moment_gcm: blade.static_moment_gcm != null ? String(blade.static_moment_gcm) : "",
    melt_number: blade.melt_number ?? "",
    part_number: blade.part_number ?? "",
    nomenclature: blade.nomenclature ?? "",
    work_order_number: blade.work_order_number ?? "",
    shop_order_number: blade.shop_order_number ?? "",
    engine_number: blade.engine_number ?? "",
  };
}

// ─── ModifyBladesPanel ────────────────────────────────────────────────────────

interface ModifyBladesPanelProps {
  batchNumber: string;
  blades: BladeListItem[];
  onSubmit: (data: ModifySubmitData) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  standalone?: boolean;
  fullPage?: boolean;
}

export function ModifyBladesPanel({
  batchNumber,
  blades,
  onSubmit,
  onCancel,
  isSubmitting,
  standalone = false,
  fullPage = false,
}: ModifyBladesPanelProps) {
  const [modSearch, setModSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<EditableFields>({
    weight_grams: "",
    static_moment_gcm: "",
    melt_number: "",
    part_number: "",
    nomenclature: "",
    work_order_number: "",
    shop_order_number: "",
    engine_number: "",
  });
  const [staged, setStaged] = useState<Map<string, BladeModification>>(new Map());
  const [remarks, setRemarks] = useState("");
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  const filteredBlades = useMemo(() => {
    const q = modSearch.toLowerCase();
    return blades.filter(
      (b) =>
        !q ||
        b.serial_number.toLowerCase().includes(q) ||
        b.melt_number.toLowerCase().includes(q)
    );
  }, [blades, modSearch]);

  const handleEdit = (blade: BladeListItem) => {
    const existing = staged.get(blade.id);
    setEditingId(blade.id);
    if (existing) {
      setEditFields({
        weight_grams: existing.updated.weight_grams != null ? String(existing.updated.weight_grams) : "",
        static_moment_gcm: existing.updated.static_moment_gcm != null ? String(existing.updated.static_moment_gcm) : "",
        melt_number: existing.updated.melt_number,
        part_number: existing.updated.part_number,
        nomenclature: existing.updated.nomenclature,
        work_order_number: existing.updated.work_order_number,
        shop_order_number: existing.updated.shop_order_number,
        engine_number: existing.updated.engine_number,
      });
    } else {
      setEditFields(emptyEditFields(blade));
    }
  };

  const handleStage = (blade: BladeListItem) => {
    const existing = staged.get(blade.id);
    const original = existing?.original ?? bladeToOriginal(blade);
    const updated: BladeModification["updated"] = {
      weight_grams: editFields.weight_grams !== "" ? parseFloat(editFields.weight_grams) : (blade.weight_grams ?? null),
      static_moment_gcm: editFields.static_moment_gcm !== "" ? parseFloat(editFields.static_moment_gcm) : (blade.static_moment_gcm ?? null),
      melt_number: editFields.melt_number || (blade.melt_number ?? ""),
      part_number: editFields.part_number || (blade.part_number ?? ""),
      nomenclature: editFields.nomenclature || (blade.nomenclature ?? ""),
      work_order_number: editFields.work_order_number || (blade.work_order_number ?? ""),
      shop_order_number: editFields.shop_order_number || (blade.shop_order_number ?? ""),
      engine_number: editFields.engine_number || (blade.engine_number ?? ""),
    };

    const hasChange =
      updated.weight_grams !== original.weight_grams ||
      updated.static_moment_gcm !== original.static_moment_gcm ||
      updated.melt_number !== original.melt_number ||
      updated.part_number !== original.part_number ||
      updated.nomenclature !== original.nomenclature ||
      updated.work_order_number !== original.work_order_number ||
      updated.shop_order_number !== original.shop_order_number ||
      updated.engine_number !== original.engine_number;

    setStaged((prev) => {
      const next = new Map(prev);
      if (hasChange) {
        next.set(blade.id, { blade_id: blade.id, serial_number: blade.serial_number, original, updated });
      } else {
        next.delete(blade.id);
      }
      return next;
    });
    setEditingId(null);
  };

  const setField = (key: keyof EditableFields, value: string) => {
    setEditFields((prev) => ({ ...prev, [key]: value }));
  };

  const canSubmit = staged.size > 0 && remarks.trim().length > 0;

  const inner = (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <Pencil className="w-4 h-4 text-amber-500 flex-shrink-0" />
        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
          Modify Blades —{" "}
          <span className="font-mono text-orange-500">{batchNumber}</span>
        </p>
        <span className="text-xs text-slate-400 dark:text-slate-500">
          Click <strong>Edit</strong> on a blade row to correct any field
        </span>
      </div>

      {blades.length === 0 && (
        <div className="rounded-lg bg-slate-50 dark:bg-slate-700/30 p-6 text-center text-sm text-slate-400 dark:text-slate-500">
          No blades found for this batch.
        </div>
      )}

      {blades.length > 0 && (
        <>
          {/* Search */}
          <div className="relative max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
            <Input
              value={modSearch}
              onChange={(e) => setModSearch(e.target.value)}
              placeholder="Search serial or melt…"
              className="pl-8 h-8 text-xs bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
            />
          </div>

          {/* Blade table — 6 columns only; all fields editable via inline form */}
          <div className={cn("rounded-lg border border-slate-200 dark:border-slate-700/50 overflow-x-auto", !fullPage && "max-h-72 overflow-y-auto")}>
            <table className="w-full text-xs relative">
              <thead className="bg-slate-100 dark:bg-slate-800 sticky top-0 z-20 shadow-sm">
                <tr>
                  {["Serial No.", "Melt No.", "Weight (g)", "SM (g·cm)", "Status", ""].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700/30">
                {filteredBlades.map((blade, idx) => {
                  const isEditing = editingId === blade.id;
                  const isStaged = staged.has(blade.id);
                  const mod = staged.get(blade.id);

                  const numDiff = (
                    orig: number | null | undefined,
                    upd: number | null | undefined,
                    fallback: string
                  ) => {
                    if (isStaged && mod && orig !== upd) {
                      return (
                        <>
                          <span className="line-through text-slate-400">{orig?.toFixed(2) ?? "—"}</span>
                          {" → "}
                          <strong className="text-emerald-600 dark:text-emerald-400">{upd?.toFixed(2) ?? "—"}</strong>
                        </>
                      );
                    }
                    return <>{fallback}</>;
                  };

                  const strDiff = (field: keyof BladeModification["original"], display: string) => {
                    if (isStaged && mod) {
                      const orig = mod.original[field];
                      const upd = mod.updated[field];
                      if (orig !== upd) {
                        return (
                          <>
                            <span className="line-through text-slate-400">{orig != null ? String(orig) : "—"}</span>
                            {" → "}
                            <strong className="text-emerald-600 dark:text-emerald-400">{upd != null ? String(upd) : "—"}</strong>
                          </>
                        );
                      }
                    }
                    return <>{display}</>;
                  };

                  return (
                    <>
                      <tr
                        key={blade.id}
                        className={cn(
                          "transition-colors",
                          isEditing && "bg-amber-50 dark:bg-amber-900/10",
                          isStaged && !isEditing && "bg-emerald-50/60 dark:bg-emerald-900/10",
                          !isEditing && !isStaged &&
                            (idx % 2 === 0 ? "bg-white dark:bg-transparent" : "bg-slate-50/60 dark:bg-slate-800/20")
                        )}
                      >
                        <td className="px-3 py-2 font-mono font-medium text-orange-500 dark:text-orange-400 whitespace-nowrap">
                          {blade.serial_number}
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300 whitespace-nowrap">
                          {strDiff("melt_number", blade.melt_number ?? "—")}
                        </td>
                        <td className="px-3 py-2 font-mono tabular-nums text-slate-700 dark:text-slate-200 whitespace-nowrap">
                          {numDiff(mod?.original.weight_grams, mod?.updated.weight_grams, blade.weight_grams?.toFixed(2) ?? "—")}
                        </td>
                        <td className="px-3 py-2 font-mono tabular-nums text-slate-700 dark:text-slate-200 whitespace-nowrap">
                          {numDiff(mod?.original.static_moment_gcm, mod?.updated.static_moment_gcm, blade.static_moment_gcm?.toFixed(2) ?? "—")}
                        </td>
                        <td className="px-3 py-2">
                          <BladeStatusBadge status={blade.status} />
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          {isStaged && !isEditing ? (
                            <div className="flex items-center justify-end gap-1">
                              <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">Staged</span>
                              <Button
                                size="sm" variant="ghost"
                                className="h-6 px-1.5 text-xs text-amber-500 hover:text-amber-700"
                                onClick={() => handleEdit(blade)}
                              >
                                Edit
                              </Button>
                              <Button
                                size="sm" variant="ghost"
                                className="h-6 w-6 p-0 text-slate-400 hover:text-red-500"
                                onClick={() => setStaged((prev) => { const n = new Map(prev); n.delete(blade.id); return n; })}
                              >
                                <X className="w-3 h-3" />
                              </Button>
                            </div>
                          ) : (
                            <Button
                              size="sm" variant="ghost"
                              className={cn(
                                "h-7 px-2 text-xs",
                                isEditing
                                  ? "text-slate-500 hover:text-slate-700"
                                  : "text-amber-600 dark:text-amber-400 hover:text-amber-700 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                              )}
                              onClick={() => { if (isEditing) setEditingId(null); else handleEdit(blade); }}
                            >
                              {isEditing ? "Cancel" : "Edit"}
                            </Button>
                          )}
                        </td>
                      </tr>

                      {/* Inline edit row — all fields in a grid, no horizontal scroll */}
                      {isEditing && (
                        <tr key={`${blade.id}-edit`} className="bg-amber-50 dark:bg-amber-900/10">
                          <td colSpan={6} className="px-3 py-4">
                            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                              {/* Numeric fields */}
                              <div className="space-y-1">
                                <Label className="text-xs text-slate-600 dark:text-slate-300 font-medium">Weight (g)</Label>
                                <Input
                                  type="number" step="0.01"
                                  value={editFields.weight_grams}
                                  onChange={(e) => setField("weight_grams", e.target.value)}
                                  className="h-8 text-xs bg-white dark:bg-slate-700 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
                                />
                              </div>
                              <div className="space-y-1">
                                <Label className="text-xs text-slate-600 dark:text-slate-300 font-medium">Static Moment (g·cm)</Label>
                                <Input
                                  type="number" step="0.01"
                                  value={editFields.static_moment_gcm}
                                  onChange={(e) => setField("static_moment_gcm", e.target.value)}
                                  className="h-8 text-xs bg-white dark:bg-slate-700 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
                                />
                              </div>
                              {/* Text fields */}
                              {(["melt_number", "part_number", "work_order_number", "shop_order_number", "engine_number", "nomenclature"] as const).map((field) => (
                                <div key={field} className="space-y-1">
                                  <Label className="text-xs text-slate-600 dark:text-slate-300 font-medium">
                                    {FIELD_LABELS[field]}
                                  </Label>
                                  <Input
                                    value={editFields[field]}
                                    onChange={(e) => setField(field, e.target.value)}
                                    className="h-8 text-xs bg-white dark:bg-slate-700 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white"
                                  />
                                </div>
                              ))}
                            </div>
                            <div className="mt-3">
                              <Button
                                size="sm"
                                className="h-8 bg-amber-500 hover:bg-amber-400 text-white text-xs"
                                onClick={() => handleStage(blade)}
                              >
                                <Check className="w-3 h-3 mr-1" />
                                Stage Changes
                              </Button>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Staged summary */}
          {staged.size > 0 && (
            <div className="rounded-lg bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-700/40 p-3 space-y-2">
              <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                {staged.size} blade{staged.size !== 1 ? "s" : ""} staged for modification
              </p>
              {Array.from(staged.values()).map((m) => (
                <div key={m.blade_id} className="space-y-0.5">
                  <span className="text-xs font-semibold font-mono text-orange-500 dark:text-orange-400">
                    {m.serial_number}
                  </span>
                  <div className="ml-3 flex flex-wrap gap-x-4 gap-y-0.5 text-xs font-mono text-slate-600 dark:text-slate-300">
                    {(Object.keys(FIELD_LABELS) as Array<keyof typeof FIELD_LABELS>).map((field) => {
                      const orig = m.original[field as keyof BladeModification["original"]];
                      const upd = m.updated[field as keyof BladeModification["updated"]];
                      if (orig === upd) return null;
                      return (
                        <span key={field}>
                          {FIELD_LABELS[field]}:{" "}
                          <span className="line-through text-slate-400">{orig != null ? String(orig) : "—"}</span>
                          {" → "}
                          <strong className="text-emerald-600 dark:text-emerald-400">{upd != null ? String(upd) : "—"}</strong>
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Remarks */}
          <div className="space-y-1">
            <Label className="text-xs font-medium text-slate-600 dark:text-slate-300">
              Remarks <span className="text-red-500">*</span>
              <span className="ml-1 font-normal text-slate-400 dark:text-slate-500">
                — describe what was changed and why
              </span>
            </Label>
            <Textarea
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              placeholder="e.g. Corrected weight for B1-002 after re-weighing on calibrated scale"
              className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white min-h-[70px] text-sm"
            />
          </div>

          {/* Submit */}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={!canSubmit || isSubmitting}
              className="bg-amber-600 hover:bg-amber-500 text-white"
              onClick={() => onSubmit({ modifications: Array.from(staged.values()), remarks })}
            >
              {isSubmitting && <Loader2 className="w-3 h-3 animate-spin mr-1.5" />}
              Submit Modifications ({staged.size})
            </Button>
            <Button
              size="sm" variant="ghost"
              onClick={() => {
                if (staged.size > 0) {
                  setShowCancelConfirm(true);
                } else {
                  onCancel();
                }
              }}
              className="text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            >
              Cancel
            </Button>
          </div>
        </>
      )}

      <Dialog open={showCancelConfirm} onOpenChange={setShowCancelConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard Changes?</DialogTitle>
            <DialogDescription>
              Are you sure you want to cancel? You have {staged.size} unsaved modification{staged.size !== 1 && "s"} that will be lost.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">Back to editing</Button>
            </DialogClose>
            <Button
              variant="destructive"
              onClick={() => {
                setShowCancelConfirm(false);
                onCancel();
              }}
            >
              Discard changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );

  if (standalone) {
    return (
      <div className="rounded-xl border border-amber-200 dark:border-amber-700/40 bg-amber-50/40 dark:bg-amber-900/5 p-4">
        {inner}
      </div>
    );
  }

  return (
    <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
      {inner}
    </div>
  );
}
