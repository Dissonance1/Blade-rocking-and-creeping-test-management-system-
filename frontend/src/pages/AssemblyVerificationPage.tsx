import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Wifi,
  WifiOff,
  Scale,
  QrCode,
  ScanLine,
  Loader2,
  ChevronRight,
  Zap,
  ClipboardCheck,
  Hash,
  Tag,
  Gauge,
  Wrench,
  Camera,
  Pencil,
  Check,
  Lock,
  Unlock,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";

import { bladeService } from "@/services/bladeService";
import { assemblyService } from "@/services/assemblyService";
import { batchService } from "@/services/batchService";
import { useWeighingSocket } from "@/hooks/useWeighingSocket";
import type { BladeListItem } from "@/types";
import type {
  BladeVerifyResponse,
  BladeVerifyRequest,
  FieldValidation,
} from "@/types/assembly";
import { cn } from "@/utils/cn";
import { toast } from "sonner";
import CameraScanner, { type ScanMode } from "@/components/common/CameraScanner";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const ASSEMBLY_STATUSES = new Set([
  "ASSEMBLY_RECEIVED",
  "ASSEMBLY_VERIFIED",
  "REJECTED",
]);

function verificationStatusOf(blade: BladeListItem): "pending" | "verified" | "rejected" | "other" {
  if (blade.status === "ASSEMBLY_RECEIVED") return "pending";
  if (blade.status === "ASSEMBLY_VERIFIED") return "verified";
  if (blade.status === "REJECTED") return "rejected";
  return "other";
}

function matchScan(scanValue: string, serial: string): "match" | "mismatch" | "empty" {
  if (!scanValue.trim()) return "empty";
  return scanValue.trim().includes(serial) ? "match" : "mismatch";
}

// ─── Subcomponents ────────────────────────────────────────────────────────────

function HardwareIndicator({ label, connected }: { label: string; connected: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        connected
          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400"
          : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
      )}
    >
      {connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
      {label}
    </span>
  );
}

function LiveValue({ value, unit }: { value: number | null; unit: string }) {
  if (value == null) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-2 py-0.5 text-xs font-mono font-semibold animate-pulse">
      <Zap className="w-3 h-3" />
      {value.toFixed(unit === "g" ? 2 : 3)} {unit}
    </span>
  );
}

function ScanMatchBadge({ status }: { status: "match" | "mismatch" | "empty" }) {
  if (status === "empty") return null;
  if (status === "match") return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
      <CheckCircle2 className="w-3.5 h-3.5" /> Match
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600 dark:text-red-400">
      <XCircle className="w-3.5 h-3.5" /> Mismatch
    </span>
  );
}

function InfoPill({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[10px] uppercase tracking-widest font-semibold text-slate-400 dark:text-slate-500">{label}</span>
      <span className={cn("text-xs font-semibold text-slate-700 dark:text-slate-200 truncate", mono && "font-mono")}>
        {value}
      </span>
    </div>
  );
}

function OhValueCell({ label, value, unit }: { label: string; value: number | null; unit: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 bg-slate-50 dark:bg-background rounded-lg px-3 py-2 min-w-[70px]">
      <span className="text-[10px] uppercase tracking-widest font-bold text-slate-400 dark:text-slate-500">{label}</span>
      <span className="text-sm font-mono font-bold text-slate-700 dark:text-slate-200">
        {value != null ? value.toFixed(unit === "g" ? 2 : 3) : "—"}
      </span>
      <span className="text-[10px] text-slate-400">{unit}</span>
    </div>
  );
}

function FieldRow({ validation }: { validation: FieldValidation }) {
  const pass = validation.within_tolerance;
  const delta = validation.delta;
  return (
    <tr className={cn("text-xs", pass ? "" : "bg-red-50 dark:bg-red-900/10")}>
      <td className="px-3 py-2 font-medium text-slate-700 dark:text-slate-300">
        {validation.field}
      </td>
      <td className="px-3 py-2 tabular-nums text-slate-600 dark:text-slate-400 font-mono">
        {validation.oh_value != null ? validation.oh_value.toFixed(3) : "—"}
      </td>
      <td className="px-3 py-2 tabular-nums text-slate-600 dark:text-slate-400 font-mono">
        {validation.assembly_value != null ? validation.assembly_value.toFixed(3) : "—"}
      </td>
      <td className={cn("px-3 py-2 tabular-nums font-mono font-semibold", pass ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
        {delta != null ? (delta >= 0 ? `+${delta.toFixed(3)}` : delta.toFixed(3)) : "—"}
      </td>
      <td className="px-3 py-2">
        {pass ? (
          <CheckCircle2 className="w-4 h-4 text-emerald-500" />
        ) : (
          <XCircle className="w-4 h-4 text-red-500" />
        )}
      </td>
    </tr>
  );
}

function BladeRow({
  blade,
  selected,
  onClick,
}: {
  blade: BladeListItem;
  selected: boolean;
  onClick: () => void;
}) {
  const vstatus = verificationStatusOf(blade);
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-3 py-2.5 rounded-lg transition-all flex items-center gap-3 group",
        selected
          ? "bg-gradient-to-r from-orange-500 to-orange-400 text-white shadow-md shadow-orange-500/20"
          : "hover:bg-slate-50 dark:hover:bg-slate-700/60 text-slate-700 dark:text-slate-300"
      )}
    >
      <span className="shrink-0">
        {vstatus === "verified" && (
          <CheckCircle2 className={cn("w-4 h-4", selected ? "text-white" : "text-emerald-500")} />
        )}
        {vstatus === "rejected" && (
          <XCircle className={cn("w-4 h-4", selected ? "text-white" : "text-red-500")} />
        )}
        {vstatus === "pending" && (
          <div className={cn("w-4 h-4 rounded-full border-2", selected ? "border-white" : "border-amber-500")} />
        )}
        {vstatus === "other" && (
          <div className={cn("w-4 h-4 rounded-full border-2 border-dashed", selected ? "border-white/50" : "border-slate-300")} />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className={cn("text-xs font-mono font-semibold truncate", selected ? "text-white" : "")}>
          {blade.serial_number}
        </p>
        <p className={cn("text-xs truncate", selected ? "text-white/70" : "text-slate-500 dark:text-slate-400")}>
          {blade.melt_number}
        </p>
      </div>
      <ChevronRight className={cn("w-3 h-3 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity", selected && "opacity-100")} />
    </button>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

type DecisionState = "idle" | "result" | "rejecting" | "modifying";

export default function AssemblyVerificationPage() {
  const { workOrderNumber } = useParams<{ workOrderNumber: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // ── Auto-init state (useEffect placed after useQuery declarations below) ──
  const [autoInitDone, setAutoInitDone] = useState(false);

  // ── Pagination ──────────────────────────────────────────────────────────
  const [currentPage, setCurrentPage] = useState(1);

  // ── Selected blade ──────────────────────────────────────────────────────
  const [selectedBlade, setSelectedBlade] = useState<BladeListItem | null>(null);

  // ── Scan inputs ─────────────────────────────────────────────────────────
  const [qrScan, setQrScan] = useState("");
  const [ocrNumber, setOcrNumber] = useState("");
  const [meltScan, setMeltScan] = useState("");

  // ── Camera scanner modal ─────────────────────────────────────────────────
  const [activeScanMode, setActiveScanMode] = useState<ScanMode | null>(null);

  // ── Measurement fields ──────────────────────────────────────────────────
  const [weight, setWeight] = useState<string>("");
  const [weightLocked, setWeightLocked] = useState(false);

  // ── Result / decision state ─────────────────────────────────────────────
  const [verifyResult, setVerifyResult] = useState<BladeVerifyResponse | null>(null);
  const [decision, setDecision] = useState<DecisionState>("idle");
  const [rejectReason, setRejectReason] = useState("");
  const [acceptNotes, setAcceptNotes] = useState("");
  const [modRemarks, setModRemarks] = useState("");
  const [modFields, setModFields] = useState({
    melt_number: "",
    part_number: "",
    work_order_number: "",
    shop_order_number: "",
    engine_number: "",
    nomenclature: "",
    weight_grams: "",
    static_moment_gcm: "",
  });

  // ── Hardware WebSockets ─────────────────────────────────────────────────
  const { currentReading: weightReading, connected: weightConn } = useWeighingSocket();

  // Continuously track the live scale reading, mirroring the LiveValue badge above
  useEffect(() => {
    if (weightReading && !weightLocked) {
      setWeight(weightReading.value.toFixed(2));
    }
  }, [weightReading, weightLocked]);

  // Reset form when a new blade is selected
  const handleSelectBlade = useCallback((blade: BladeListItem) => {
    setSelectedBlade(blade);
    setQrScan("");
    setOcrNumber("");
    setMeltScan("");
    setWeight("");
    setWeightLocked(false);
    setVerifyResult(null);
    setDecision("idle");
    setRejectReason("");
    setAcceptNotes("");
    setModRemarks("");
    setModFields({ melt_number: "", part_number: "", work_order_number: "", shop_order_number: "", engine_number: "", nomenclature: "", weight_grams: "", static_moment_gcm: "" });
  }, []);

  // ── Data fetching ───────────────────────────────────────────────────────

  const { data: bladesData, isLoading: bladesLoading } = useQuery({
    queryKey: ["blades", "batch", workOrderNumber],
    queryFn: () => bladeService.list({ work_order_number: workOrderNumber!, limit: 200 }),
    enabled: !!workOrderNumber,
    refetchInterval: 10_000,
  });

  // Auto-init: if batch has no ASSEMBLY_RECEIVED blades yet, call receiveBatch to transition them
  useEffect(() => {
    if (!workOrderNumber || autoInitDone || bladesLoading) return;
    const hasAssemblyBlades = (bladesData?.items ?? []).some((b) =>
      ["ASSEMBLY_RECEIVED", "ASSEMBLY_VERIFIED", "REJECTED"].includes(b.status)
    );
    if (bladesData && !hasAssemblyBlades) {
      assemblyService
        .receiveBatch(workOrderNumber, {})
        .catch(() => { /* receipt may already exist */ })
        .finally(() => {
          setAutoInitDone(true);
          queryClient.invalidateQueries({ queryKey: ["blades", "batch", workOrderNumber] });
          queryClient.invalidateQueries({ queryKey: ["assembly", "progress", workOrderNumber] });
        });
    } else {
      setAutoInitDone(true);
    }
  }, [bladesData, bladesLoading, workOrderNumber, autoInitDone, queryClient]);

  const { data: progress } = useQuery({
    queryKey: ["assembly", "progress", workOrderNumber],
    queryFn: () => assemblyService.getBatchProgress(workOrderNumber!),
    enabled: !!workOrderNumber,
    refetchInterval: 5_000,
  });

  const { data: fullBlade } = useQuery({
    queryKey: ["blade", selectedBlade?.id],
    queryFn: () => bladeService.get(selectedBlade!.id),
    enabled: !!selectedBlade?.id,
  });

  // ── Derived OH measurements — prefer FINAL, fall back to latest ──────────
  const measurements = fullBlade?.measurements ?? [];
  const finalMeasurements = measurements.filter((m) => m.measurement_type === "FINAL");
  const latestMeasurement =
    finalMeasurements.length > 0
      ? finalMeasurements[finalMeasurements.length - 1]
      : measurements.length > 0
        ? measurements[measurements.length - 1]
        : null;
  const ohWeight = latestMeasurement?.weight_grams != null ? Number(latestMeasurement.weight_grams) : null;

  // ── Mutations ───────────────────────────────────────────────────────────

  const verifyMutation = useMutation({
    mutationFn: (data: BladeVerifyRequest) =>
      assemblyService.verifyBlade(selectedBlade!.id, data),
    onSuccess: (result) => {
      setVerifyResult(result);
      setDecision("result");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Verification failed";
      toast.error(msg);
    },
  });

  const acceptMutation = useMutation({
    mutationFn: () =>
      assemblyService.acceptBlade(selectedBlade!.id, { notes: acceptNotes || undefined }),
    onSuccess: () => {
      toast.success(`${selectedBlade!.serial_number} accepted`);
      queryClient.invalidateQueries({ queryKey: ["blades", "batch", workOrderNumber] });
      queryClient.invalidateQueries({ queryKey: ["assembly", "progress", workOrderNumber] });
      setDecision("idle");
      setVerifyResult(null);
      setSelectedBlade(null);
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Accept failed";
      toast.error(msg);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () =>
      assemblyService.rejectBlade(selectedBlade!.id, { notes: rejectReason }),
    onSuccess: () => {
      toast.success(`${selectedBlade!.serial_number} rejected`);
      queryClient.invalidateQueries({ queryKey: ["blades", "batch", workOrderNumber] });
      queryClient.invalidateQueries({ queryKey: ["assembly", "progress", workOrderNumber] });
      setDecision("idle");
      setVerifyResult(null);
      setSelectedBlade(null);
      setRejectReason("");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Reject failed";
      toast.error(msg);
    },
  });

  const setMakingMutation = useMutation({
    mutationFn: () => assemblyService.startSetMaking(workOrderNumber!),
    onSuccess: (res) => {
      toast.success(res.message || "Set-making initiated");
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      navigate("/assembly-queue");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to start set-making";
      toast.error(msg);
    },
  });

  const modifyMutation = useMutation({
    mutationFn: () => {
      if (!selectedBlade) throw new Error("No blade selected");
      const original = {
        melt_number: selectedBlade.melt_number ?? "",
        part_number: selectedBlade.part_number ?? "",
        work_order_number: selectedBlade.work_order_number ?? "",
        shop_order_number: selectedBlade.shop_order_number ?? "",
        engine_number: selectedBlade.engine_number ?? "",
        nomenclature: selectedBlade.nomenclature ?? "",
        weight_grams: selectedBlade.weight_grams ?? null,
        static_moment_gcm: selectedBlade.static_moment_gcm ?? null,
      };
      const updated = {
        melt_number: modFields.melt_number || original.melt_number,
        part_number: modFields.part_number || original.part_number,
        work_order_number: modFields.work_order_number || original.work_order_number,
        shop_order_number: modFields.shop_order_number || original.shop_order_number,
        engine_number: modFields.engine_number || original.engine_number,
        nomenclature: modFields.nomenclature || original.nomenclature,
        weight_grams: modFields.weight_grams !== "" ? parseFloat(modFields.weight_grams) : original.weight_grams,
        static_moment_gcm: modFields.static_moment_gcm !== "" ? parseFloat(modFields.static_moment_gcm) : original.static_moment_gcm,
      };
      return batchService.modify(workOrderNumber!, [{ blade_id: selectedBlade.id, serial_number: selectedBlade.serial_number, original, updated }], modRemarks);
    },
    onSuccess: () => {
      toast.success("Blade data saved — please re-verify with corrected values");
      queryClient.invalidateQueries({ queryKey: ["blades", "batch", workOrderNumber] });
      queryClient.invalidateQueries({ queryKey: ["blade", selectedBlade?.id] });
      setDecision("idle");
      setVerifyResult(null);
      setModRemarks("");
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to save modifications";
      toast.error(msg);
    },
  });

  // ── Submit verification ─────────────────────────────────────────────────
  const handleVerify = () => {
    if (!selectedBlade) return;
    verifyMutation.mutate({
      qr_scan_result: qrScan || undefined,
      ocr_blade_number: ocrNumber || undefined,
      assembly_weight: weight !== "" ? parseFloat(weight) : undefined,
    });
  };

  // ── Blade list (filtered to assembly-relevant statuses) ─────────────────
  const blades = (bladesData?.items ?? []).filter((b) => ASSEMBLY_STATUSES.has(b.status));
  const pendingCount = blades.filter((b) => b.status === "ASSEMBLY_RECEIVED").length;
  const verifiedCount = blades.filter((b) => b.status === "ASSEMBLY_VERIFIED").length;
  const rejectedCount = blades.filter((b) => b.status === "REJECTED").length;
  const totalExpected = progress?.total_expected ?? blades.length;
  const progressPct = totalExpected > 0 ? Math.round((verifiedCount / totalExpected) * 100) : 0;
  const setMakingReady = progress?.set_making_ready ?? false;

  // ── Suggested action colour ─────────────────────────────────────────────
  const actionColor =
    verifyResult?.suggested_action === "ACCEPT"
      ? "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20"
      : verifyResult?.suggested_action === "REJECT"
        ? "text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20"
        : "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20";

  // ── Scan match status ───────────────────────────────────────────────────
  const qrMatchStatus = selectedBlade ? matchScan(qrScan, selectedBlade.serial_number) : "empty";
  const ocrMatchStatus = selectedBlade ? matchScan(ocrNumber, selectedBlade.serial_number) : "empty";
  const meltMatchStatus = selectedBlade ? matchScan(meltScan, selectedBlade.melt_number) : "empty";

  return (
    <>
      <div className="h-full flex flex-col overflow-hidden bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
        {/* Header */}
        <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background border-b border-white/60 dark:border-white/10 shadow-sm px-4 sm:px-6 py-4">
          <div className="max-w-screen-xl mx-auto w-full flex flex-col sm:flex-row sm:items-start gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/assembly-queue")}
              className="shrink-0 self-start -ml-2 text-slate-500 hover:text-slate-800 dark:hover:text-white"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              Back
            </Button>

            <div className="flex-1 min-w-0 flex flex-col sm:flex-row flex-wrap items-start sm:items-center justify-between gap-3">
              <div className="min-w-0">
                <h1 className="text-base sm:text-lg font-bold text-slate-900 dark:text-white leading-tight truncate">
                  Blade Verification — Work Order{" "}
                  <span className="text-orange-500 font-mono">{workOrderNumber}</span>
                </h1>
                <div className="flex flex-wrap items-center gap-3 mt-1">
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {verifiedCount}/{totalExpected} verified · {rejectedCount} rejected · {pendingCount} pending
                  </span>
                  <div className="flex-1 min-w-[100px] max-w-[200px] bg-slate-200 dark:bg-background rounded-full h-1.5">
                    <div
                      className="bg-orange-500 h-1.5 rounded-full transition-all"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                  <span className="text-xs font-semibold text-orange-500">{progressPct}%</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 items-center">
                <HardwareIndicator label="Scale" connected={weightConn} />
              </div>
              {setMakingReady && (
                <Button
                  size="sm"
                  className="w-full sm:w-auto justify-center bg-emerald-600 hover:bg-emerald-500 text-white"
                  onClick={() => setMakingMutation.mutate()}
                  disabled={setMakingMutation.isPending}
                >
                  {setMakingMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-1" />
                  ) : (
                    <ClipboardCheck className="w-4 h-4 mr-1" />
                  )}
                  Start Set-Making
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 max-w-screen-xl mx-auto w-full px-4 sm:px-6 pt-4 sm:pt-6 pb-32 flex flex-col lg:flex-row gap-4 sm:gap-6 overflow-y-auto">
          {/* ── Left: blade list ── */}
          <div className="w-full lg:w-72 shrink-0 flex flex-col gap-3">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500 pl-1">
              Blades ({blades.length})
            </p>
            <div className="flex flex-col bg-white dark:bg-background p-2 rounded-2xl border border-slate-200 dark:border-slate-700/60 shadow-sm lg:flex-1 lg:min-h-0">
              <div className="max-h-72 lg:max-h-none lg:flex-1 overflow-y-auto space-y-1">
                {bladesLoading && (
                  <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading…
                  </div>
                )}
                {!bladesLoading && blades.length === 0 && !autoInitDone && (
                  <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
                    <Loader2 className="w-4 h-4 animate-spin" /> Receiving blades at Assembly…
                  </div>
                )}
                {!bladesLoading && blades.length === 0 && autoInitDone && (
                  <p className="text-sm text-slate-400 dark:text-slate-500 py-4 text-center">
                    No blades in ASSEMBLY_RECEIVED status. Check that the batch was sent from OH.
                  </p>
                )}
                {blades.slice((currentPage - 1) * 15, currentPage * 15).map((b) => (
                  <BladeRow
                    key={b.id}
                    blade={b}
                    selected={selectedBlade?.id === b.id}
                    onClick={() => handleSelectBlade(b)}
                  />
                ))}
              </div>
              {blades.length > 15 && (
                <div className="shrink-0 flex items-center justify-between mt-2 pt-2 border-t border-slate-200 dark:border-slate-700/60 px-1">
                  <Button variant="outline" size="sm" className="h-7 text-xs px-2 text-slate-600 dark:text-slate-300" disabled={currentPage === 1} onClick={() => setCurrentPage(p => Math.max(1, p - 1))}>Prev</Button>
                  <span className="text-xs font-medium text-slate-500">{currentPage} / {Math.ceil(blades.length / 15)}</span>
                  <Button variant="outline" size="sm" className="h-7 text-xs px-2 text-slate-600 dark:text-slate-300" disabled={currentPage === Math.ceil(blades.length / 15)} onClick={() => setCurrentPage(p => Math.min(Math.ceil(blades.length / 15), p + 1))}>Next</Button>
                </div>
              )}
            </div>
          </div>

          {/* ── Right: verification panel ── */}
          <div className="flex-1 min-w-0 lg:self-start flex flex-col gap-4 lg:pt-7 pb-16">
            {!selectedBlade ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-10 text-slate-400 dark:text-slate-500 bg-white dark:bg-background rounded-2xl border border-slate-200 dark:border-slate-700/60 shadow-sm">
                <div className="w-16 h-16 sm:w-24 sm:h-24 mb-6 rounded-full bg-slate-50 dark:bg-background flex items-center justify-center shadow-inner border border-slate-100 dark:border-slate-700">
                  <ScanLine className="w-8 h-8 sm:w-10 sm:h-10 text-slate-300 dark:text-slate-600" />
                </div>
                <p className="font-semibold text-lg sm:text-xl text-slate-700 dark:text-slate-300">Select a blade to verify</p>
                <p className="text-sm mt-2 max-w-sm text-center text-slate-500">
                  Each blade must be scanned, weighed, and measured before it can be accepted.
                </p>
              </div>
            ) : (
              <div className="space-y-4">

                {/* ── Blade identity card ── */}
                <Card className="bg-white/80 dark:bg-background backdrop-blur-md border border-white/60 dark:border-white/10 rounded-2xl shadow-lg shadow-slate-200/50 dark:shadow-black/20">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      {/* Left: serial + melt + type badge */}
                      <div className="flex items-start gap-4 min-w-0">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <h2 className="text-lg sm:text-xl font-bold font-mono text-slate-900 dark:text-white break-all">
                              {selectedBlade.serial_number}
                            </h2>
                            <span className={cn(
                              "px-2 py-0.5 rounded-full text-xs font-bold tracking-wide",
                              fullBlade?.blade_type === "HPTR"
                                ? "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400"
                                : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                            )}>
                              {fullBlade?.blade_type ?? "—"}
                            </span>
                            {selectedBlade.status !== "ASSEMBLY_RECEIVED" && (
                              <span className={cn(
                                "px-2 py-0.5 rounded-full text-xs font-semibold",
                                selectedBlade.status === "ASSEMBLY_VERIFIED"
                                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                                  : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                              )}>
                                {selectedBlade.status === "ASSEMBLY_VERIFIED" ? "Already Verified" : "Rejected"}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                            {selectedBlade.nomenclature}
                          </p>
                        </div>
                      </div>

                      {/* Right: key fields grid */}
                      <div className="flex flex-wrap gap-x-6 gap-y-3">
                        <InfoPill label="Melt Number" value={selectedBlade.melt_number} mono />
                        <InfoPill label="Part Number" value={selectedBlade.part_number} mono />
                        <InfoPill label="Work Order" value={selectedBlade.work_order_number} mono />
                        <InfoPill label="Engine No." value={selectedBlade.engine_number ?? fullBlade?.engine_number ?? undefined} mono />
                        <InfoPill label="Eng. Hours" value={fullBlade?.engine_hours ?? undefined} />
                        <InfoPill label="Comp. Hours" value={fullBlade?.component_hours ?? undefined} />
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* ── OH Reference snapshot ── */}
                <Card className="bg-gradient-to-br from-orange-50 to-orange-100/50 dark:from-orange-900/20 dark:to-orange-900/5 backdrop-blur-md border border-orange-200/60 dark:border-orange-800/50 rounded-2xl shadow-md shadow-orange-500/5">
                  <CardContent className="p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Gauge className="w-4 h-4 text-orange-500" />
                      <p className="text-xs font-bold uppercase tracking-widest text-orange-600 dark:text-orange-400">
                        OH Reference Values
                      </p>
                      {!latestMeasurement && (
                        <span className="ml-auto text-xs text-slate-400 dark:text-slate-500 italic">
                          No OH measurements recorded
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <OhValueCell label="Weight" value={ohWeight} unit="g" />
                      {latestMeasurement && (
                        <div className="flex flex-col justify-end ml-auto text-right">
                          <span className="text-[10px] text-slate-400 dark:text-slate-500">Tolerance</span>
                          <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">Weight ±0.5 g</span>
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>

                {selectedBlade.status === "ASSEMBLY_RECEIVED" && decision !== "result" && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {/* ── Identity scan ── */}
                    <Card className="bg-white/80 dark:bg-background backdrop-blur-md border border-white/60 dark:border-white/10 rounded-2xl shadow-lg shadow-slate-200/50 dark:shadow-black/20">
                      <CardContent className="p-4 space-y-4">
                        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500 flex items-center gap-1">
                          <QrCode className="w-3 h-3" /> Identity Scan
                        </p>

                        {/* QR Code */}
                        <div>
                          <div className="flex items-center justify-between mb-1.5">
                            <label className="text-xs font-medium text-slate-600 dark:text-slate-400 flex items-center gap-1">
                              <Hash className="w-3 h-3" /> QR Code
                            </label>
                            <ScanMatchBadge status={qrMatchStatus} />
                          </div>
                          <div className="flex gap-2">
                            <Input
                              value={qrScan}
                              onChange={(e) => setQrScan(e.target.value)}
                              placeholder="Scan QR or type serial number…"
                              className={cn(
                                "font-mono text-sm bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600",
                                qrMatchStatus === "match" && "border-emerald-400 dark:border-emerald-500",
                                qrMatchStatus === "mismatch" && "border-red-400 dark:border-red-500"
                              )}
                            />
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0 border-orange-400 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 px-3"
                              onClick={() => setActiveScanMode("qr")}
                              title="Open camera scanner"
                            >
                              <Camera className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>

                        {/* OCR Blade Number */}
                        <div>
                          <div className="flex items-center justify-between mb-1.5">
                            <label className="text-xs font-medium text-slate-600 dark:text-slate-400 flex items-center gap-1">
                              <ScanLine className="w-3 h-3" /> OCR Blade Number
                            </label>
                            <ScanMatchBadge status={ocrMatchStatus} />
                          </div>
                          <div className="flex gap-2">
                            <Input
                              value={ocrNumber}
                              onChange={(e) => setOcrNumber(e.target.value)}
                              placeholder="OCR-captured or manually entered…"
                              className={cn(
                                "font-mono text-sm bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600",
                                ocrMatchStatus === "match" && "border-emerald-400 dark:border-emerald-500",
                                ocrMatchStatus === "mismatch" && "border-red-400 dark:border-red-500"
                              )}
                            />
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0 border-orange-400 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 px-3"
                              onClick={() => setActiveScanMode("serial")}
                              title="Open OCR camera scanner"
                            >
                              <Camera className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>

                        {/* Melt Number */}
                        <div>
                          <div className="flex items-center justify-between mb-1.5">
                            <label className="text-xs font-medium text-slate-600 dark:text-slate-400 flex items-center gap-1">
                              <Wrench className="w-3 h-3" /> Melt Number
                            </label>
                            <ScanMatchBadge status={meltMatchStatus} />
                          </div>
                          <div className="flex gap-2">
                            <Input
                              value={meltScan}
                              onChange={(e) => setMeltScan(e.target.value)}
                              placeholder="Scan or enter melt number…"
                              className={cn(
                                "font-mono text-sm bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600",
                                meltMatchStatus === "match" && "border-emerald-400 dark:border-emerald-500",
                                meltMatchStatus === "mismatch" && "border-red-400 dark:border-red-500"
                              )}
                            />
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="shrink-0 border-orange-400 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 px-3"
                              onClick={() => setActiveScanMode("melt")}
                              title="Open melt number scanner"
                            >
                              <Camera className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>

                        {/* Expected values hint */}
                        <div className="rounded-lg bg-slate-50 dark:bg-background border border-slate-200 dark:border-slate-700 p-3 space-y-1.5">
                          <p className="text-[10px] uppercase tracking-widest font-bold text-slate-400 dark:text-slate-500">Expected on Blade Tag</p>
                          <div className="flex items-center gap-2">
                            <Tag className="w-3 h-3 text-slate-400 shrink-0" />
                            <span className="text-xs font-mono text-slate-600 dark:text-slate-300">
                              {selectedBlade.serial_number}
                            </span>
                            <span className="text-[10px] text-slate-400">Serial</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <Wrench className="w-3 h-3 text-slate-400 shrink-0" />
                            <span className="text-xs font-mono text-slate-600 dark:text-slate-300">
                              {selectedBlade.melt_number}
                            </span>
                            <span className="text-[10px] text-slate-400">Melt</span>
                          </div>
                        </div>
                      </CardContent>
                    </Card>

                    {/* ── Weight ── */}
                    <Card className="bg-white/80 dark:bg-background backdrop-blur-md border border-white/60 dark:border-white/10 rounded-2xl shadow-lg shadow-slate-200/50 dark:shadow-black/20">
                      <CardContent className="p-4 space-y-4">
                        <div className="flex items-center justify-between">
                          <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500 flex items-center gap-1">
                            <Scale className="w-3 h-3" /> Assembly Weight
                          </p>
                          {weightReading && (
                            <LiveValue value={weightReading.value} unit="g" />
                          )}
                        </div>

                        {/* OH reference row */}
                        <div className="flex items-center justify-between rounded-lg bg-orange-50 dark:bg-orange-900/10 border border-orange-200 dark:border-orange-800/40 px-3 py-2">
                          <span className="text-xs text-slate-500 dark:text-slate-400">OH recorded</span>
                          <span className="text-sm font-mono font-bold text-slate-700 dark:text-slate-200">
                            {ohWeight != null ? `${ohWeight.toFixed(2)} g` : "—"}
                          </span>
                        </div>

                        <div className="flex gap-2">
                          <Input
                            type="number"
                            step="0.01"
                            value={weight}
                            readOnly={weightLocked}
                            onChange={(e) => {
                              if (weightLocked) return;
                              setWeight(e.target.value);
                            }}
                            placeholder="0.00"
                            className="font-mono text-sm bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600"
                          />
                          <span className="self-center text-xs text-slate-500 font-mono">g</span>
                          <Button
                            size="sm"
                            variant="outline"
                            title={weightLocked ? "Unlock" : "Lock"}
                            className={cn(
                              "shrink-0 h-9 px-2",
                              weightLocked
                                ? "border-amber-400 text-amber-600 dark:text-amber-400"
                                : "border-emerald-400 text-emerald-600 dark:text-emerald-400"
                            )}
                            onClick={() => setWeightLocked((prev) => !prev)}
                          >
                            {weightLocked ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}
                          </Button>
                        </div>

                        {weight !== "" && ohWeight != null && (
                          <p className={cn(
                            "text-xs font-mono",
                            Math.abs(parseFloat(weight) - ohWeight) <= 0.5
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-red-600 dark:text-red-400"
                          )}>
                            Δ {(parseFloat(weight) - ohWeight) >= 0 ? "+" : ""}
                            {(parseFloat(weight) - ohWeight).toFixed(2)} g
                            {Math.abs(parseFloat(weight) - ohWeight) <= 0.5 ? " ✓ within tolerance" : " ✗ out of tolerance"}
                          </p>
                        )}
                      </CardContent>
                    </Card>

                    {/* ── Submit button ── */}
                    <div className="lg:col-span-2 flex justify-end">
                      <Button
                        onClick={handleVerify}
                        disabled={verifyMutation.isPending}
                        className="w-full sm:w-auto justify-center bg-orange-500 hover:bg-orange-400 text-white px-8"
                      >
                        {verifyMutation.isPending ? (
                          <Loader2 className="w-4 h-4 animate-spin mr-2" />
                        ) : (
                          <ClipboardCheck className="w-4 h-4 mr-2" />
                        )}
                        Submit Verification
                      </Button>
                    </div>
                  </div>
                )}

                {/* ── Validation result + reject / modify form ── */}
                {verifyResult && (decision === "result" || decision === "rejecting" || decision === "modifying") && (
                  <div className="space-y-4">
                    {decision !== "modifying" && <div className="flex flex-wrap gap-3">
                      <span className={cn(
                        "inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium",
                        verifyResult.serial_number_match
                          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                          : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                      )}>
                        {verifyResult.serial_number_match ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                        QR Match
                      </span>
                      <span className={cn(
                        "inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium",
                        verifyResult.ocr_match
                          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                          : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                      )}>
                        {verifyResult.ocr_match ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                        OCR Match
                      </span>
                      <span className={cn("inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold ml-auto", actionColor)}>
                        Suggested: {verifyResult.suggested_action}
                      </span>
                    </div>}

                    {decision !== "modifying" && (
                      <Card className="bg-white dark:bg-background border-slate-200 dark:border-slate-700/60">
                        <CardContent className="p-0 overflow-x-auto">
                          <table className="w-full text-sm whitespace-nowrap">
                            <thead className="bg-slate-100 dark:bg-background">
                              <tr>
                                {["Field", "OH Value", "Assembly Value", "Delta", "Status"].map((h) => (
                                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                                    {h}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                              {verifyResult.validations.map((v) => (
                                <FieldRow key={v.field} validation={v} />
                              ))}
                            </tbody>
                          </table>
                        </CardContent>
                      </Card>
                    )}

                    {decision === "result" && (
                      <div className="flex flex-wrap gap-3 pt-1">
                        <Button
                          className="bg-emerald-600 hover:bg-emerald-500 text-white"
                          disabled={acceptMutation.isPending}
                          onClick={() => acceptMutation.mutate()}
                        >
                          {acceptMutation.isPending ? (
                            <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                          ) : (
                            <CheckCircle2 className="w-4 h-4 mr-1.5" />
                          )}
                          Accept
                        </Button>
                        <Button
                          variant="outline"
                          className="border-2 border-red-500 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
                          onClick={() => setDecision("rejecting")}
                        >
                          <XCircle className="w-4 h-4 mr-1.5" />
                          Reject
                        </Button>
                        <Button
                          variant="outline"
                          className="border-amber-400 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                          onClick={() => {
                            if (selectedBlade) {
                              setModFields({
                                melt_number: selectedBlade.melt_number ?? "",
                                part_number: selectedBlade.part_number ?? "",
                                work_order_number: selectedBlade.work_order_number ?? "",
                                shop_order_number: selectedBlade.shop_order_number ?? "",
                                engine_number: selectedBlade.engine_number ?? "",
                                nomenclature: selectedBlade.nomenclature ?? "",
                                weight_grams: selectedBlade.weight_grams != null ? String(selectedBlade.weight_grams) : "",
                                static_moment_gcm: selectedBlade.static_moment_gcm != null ? String(selectedBlade.static_moment_gcm) : "",
                              });
                            }
                            setDecision("modifying");
                          }}
                        >
                          <Pencil className="w-4 h-4 mr-1.5" />
                          Modify Data
                        </Button>
                        <Button
                          variant="ghost"
                          className="text-slate-500 ml-auto"
                          onClick={() => { setDecision("idle"); setVerifyResult(null); }}
                        >
                          Re-measure
                        </Button>
                      </div>
                    )}

                    {decision === "rejecting" && (
                      <div className="space-y-3 pt-1 border-t border-slate-200 dark:border-slate-700">
                        <p className="text-sm font-medium text-red-600 dark:text-red-400">
                          Rejection Reason (required)
                        </p>
                        <Textarea
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          placeholder="Describe why this blade is being rejected…"
                          className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 min-h-[80px]"
                        />
                        <div className="flex gap-3">
                          <Button
                            className={cn(
                              "text-white",
                              (!rejectReason.trim() || rejectMutation.isPending)
                                ? "bg-slate-400 dark:bg-background cursor-not-allowed opacity-100"
                                : "bg-red-600 hover:bg-red-500"
                            )}
                            disabled={!rejectReason.trim() || rejectMutation.isPending}
                            onClick={() => rejectMutation.mutate()}
                          >
                            {rejectMutation.isPending ? (
                              <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                            ) : (
                              <XCircle className="w-4 h-4 mr-1.5" />
                            )}
                            Confirm Rejection
                          </Button>
                          <Button variant="ghost" onClick={() => setDecision("result")} className="text-slate-500">
                            Cancel
                          </Button>
                        </div>
                      </div>
                    )}

                    {decision === "modifying" && (
                      <div className="space-y-4 pt-2 border-t border-amber-200 dark:border-amber-700/50">
                        <p className="text-sm font-semibold text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
                          <Pencil className="w-4 h-4" />
                          Modify Blade Data — {selectedBlade?.serial_number}
                        </p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          Correct the blade's recorded values. After saving, you will re-verify with the updated data.
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                          {(["melt_number", "part_number", "work_order_number", "shop_order_number", "engine_number", "nomenclature"] as const).map((field) => (
                            <div key={field} className="space-y-1">
                              <label className="text-xs font-medium text-slate-600 dark:text-slate-400 block">
                                {field === "melt_number" ? "Melt No." : field === "part_number" ? "Part No." : field === "work_order_number" ? "Work Order" : field === "shop_order_number" ? "Shop Order" : field === "engine_number" ? "Engine No." : "Nomenclature"}
                              </label>
                              <Input
                                value={modFields[field]}
                                onChange={(e) => setModFields((prev) => ({ ...prev, [field]: e.target.value }))}
                                className="h-8 text-xs bg-white dark:bg-background border-slate-300 dark:border-slate-600"
                              />
                            </div>
                          ))}
                          <div className="space-y-1">
                            <label className="text-xs font-medium text-slate-600 dark:text-slate-400 block">Weight (g)</label>
                            <Input
                              type="number" step="0.01"
                              value={modFields.weight_grams}
                              onChange={(e) => setModFields((prev) => ({ ...prev, weight_grams: e.target.value }))}
                              className="h-8 text-xs bg-white dark:bg-background border-slate-300 dark:border-slate-600"
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="text-xs font-medium text-slate-600 dark:text-slate-400 block">Static Moment (g·cm)</label>
                            <Input
                              type="number" step="0.01"
                              value={modFields.static_moment_gcm}
                              onChange={(e) => setModFields((prev) => ({ ...prev, static_moment_gcm: e.target.value }))}
                              className="h-8 text-xs bg-white dark:bg-background border-slate-300 dark:border-slate-600"
                            />
                          </div>
                        </div>
                        <div className="space-y-1.5">
                          <label className="text-xs font-medium text-amber-600 dark:text-amber-400 block">
                            Reason for modification <span className="text-red-500">*</span>
                          </label>
                          <Textarea
                            value={modRemarks}
                            onChange={(e) => setModRemarks(e.target.value)}
                            placeholder="e.g. Corrected melt number after physical tag re-scan…"
                            className="bg-slate-50 dark:bg-background border-amber-300 dark:border-amber-700/50 min-h-[70px] text-sm"
                          />
                        </div>
                        <div className="flex gap-3">
                          <Button
                            className="bg-amber-500 hover:bg-amber-400 text-white"
                            disabled={!modRemarks.trim() || modifyMutation.isPending}
                            onClick={() => modifyMutation.mutate()}
                          >
                            {modifyMutation.isPending ? (
                              <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                            ) : (
                              <Check className="w-4 h-4 mr-1.5" />
                            )}
                            Save Changes
                          </Button>
                          <Button variant="ghost" onClick={() => setDecision("result")} className="text-slate-500">
                            Cancel
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Already-verified / rejected — read-only summary */}
                {selectedBlade.status === "ASSEMBLY_VERIFIED" && (
                  <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-700 p-4 text-sm text-emerald-700 dark:text-emerald-400">
                    <CheckCircle2 className="w-5 h-5 inline mr-2" />
                    This blade has already been verified and accepted. Select a pending blade to continue.
                  </div>
                )}
                {selectedBlade.status === "REJECTED" && (
                  <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 p-4 text-sm text-red-700 dark:text-red-400">
                    <XCircle className="w-5 h-5 inline mr-2" />
                    This blade was rejected at Assembly. Select a pending blade to continue.
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Camera scanner modal */}
      {activeScanMode && (
        <CameraScanner
          mode={activeScanMode}
          onResult={(value) => {
            if (activeScanMode === "qr") setQrScan(value);
            else if (activeScanMode === "serial") setOcrNumber(value);
            else if (activeScanMode === "melt") setMeltScan(value);
          }}
          onClose={() => setActiveScanMode(null)}
        />
      )}
    </>
  );
}
