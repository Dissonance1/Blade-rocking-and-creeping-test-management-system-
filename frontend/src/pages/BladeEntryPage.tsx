import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Check,
  Plus,
  Trash2,
  Loader2,
  AlertCircle,
  ClipboardList,
  Ruler,
  Eye,
  Pencil,
  Sparkles,
  X,
  Camera,
  Scale,
  Lock,
  Unlock,
  Wifi,
  WifiOff,
  RefreshCw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

import { bladeService } from "@/services/bladeService";
import { ocrService, type OcrScanResult } from "@/services/ocrService";
import { extractApiError } from "@/services/api";
import { useAuthStore } from "@/store/authStore";
import { cn } from "@/utils/cn";
import { useDTISocket } from "@/hooks/useDTISocket";

// ─── Weighing machine hook ────────────────────────────────────────────────────

type ScaleStatus = "idle" | "connecting" | "connected" | "disconnected";

function useWeighingScale(
  onWeight: (kg: number) => void
): { status: ScaleStatus; locked: boolean; toggleLock: () => void } {
  const token = useAuthStore((s) => s.accessToken);
  const [status, setStatus] = useState<ScaleStatus>("idle");
  const [locked, setLocked] = useState(false);
  const lockedRef = useRef(false);
  const statusRef = useRef<ScaleStatus>("idle");
  const wsRef = useRef<WebSocket | null>(null);

  const toggleLock = useCallback(() => {
    lockedRef.current = !lockedRef.current;
    setLocked(lockedRef.current);
  }, []);

  useEffect(() => {
    if (!token) return;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsBase = import.meta.env.VITE_WS_URL || `${proto}//${window.location.host}`;
    const url = `${wsBase}/api/v1/weighing/ws?token=${token}`;

    let alive = true;
    let ws: WebSocket;

    function connect() {
      ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data as string) as { type: string; status?: string; value?: number };
          if (msg.type === "status") {
            const s = msg.status;
            if (s === "unavailable") {
              statusRef.current = "idle";
              setStatus("idle");
              ws.close();
            } else {
              statusRef.current = (s as ScaleStatus) ?? "idle";
              setStatus(statusRef.current);
            }
          } else if (msg.type === "weight" && msg.value != null) {
            if (!lockedRef.current) onWeight(msg.value);
          } else if (msg.type === "ping") {
            ws.send(JSON.stringify({ type: "pong" }));
          }
        } catch { /* ignore malformed frames */ }
      };

      ws.onclose = () => {
        if (alive && (statusRef.current === "connected" || statusRef.current === "disconnected")) {
          statusRef.current = "disconnected";
          setStatus("disconnected");
          setTimeout(connect, 5000);
        }
      };

      ws.onerror = () => { /* onclose fires after onerror */ };
    }

    connect();

    return () => {
      alive = false;
      ws?.close();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return { status, locked, toggleLock };
}

// ─── OCR scan state ───────────────────────────────────────────────────────────

interface ScanState {
  scanning: boolean;
  result: OcrScanResult | null;
  preview: string | null;
  applied: boolean;
}

const EMPTY_SCAN: ScanState = { scanning: false, result: null, preview: null, applied: false };

// ─── OCR folder — File System Access API + IndexedDB persistence ─────────────
// The user picks a folder once; all images + JSON sidecars go there silently.
// The directory handle is stored in IndexedDB so it survives page reloads.

const IDB_NAME  = "ocr_storage";
const IDB_STORE = "settings";
const IDB_KEY   = "dirHandle";

function openIDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(IDB_STORE);
    req.onsuccess  = () => resolve(req.result);
    req.onerror    = () => reject(req.error);
  });
}

async function idbGet<T>(key: string): Promise<T | null> {
  try {
    const db = await openIDB();
    return new Promise((resolve) => {
      const req = db.transaction(IDB_STORE, "readonly").objectStore(IDB_STORE).get(key);
      req.onsuccess = () => resolve((req.result as T) ?? null);
      req.onerror   = () => resolve(null);
    });
  } catch { return null; }
}

async function idbSet(key: string, value: unknown): Promise<void> {
  try {
    const db = await openIDB();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror    = () => reject(tx.error);
    });
  } catch { /* ignore */ }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const fsa = window as any; // FileSystem Access API — typed loosely for TS compat

function useOcrFolder() {
  const dirRef   = useRef<FileSystemDirectoryHandle | null>(null);
  const [folderName, setFolderName] = useState<string | null>(null);

  // Restore saved handle on mount and verify permission still holds
  useEffect(() => {
    idbGet<FileSystemDirectoryHandle>(IDB_KEY).then(async (handle) => {
      if (!handle) return;
      try {
        // queryPermission is part of the FSA spec but missing from older TS DOM types
        const perm = await (handle as any).queryPermission({ mode: "readwrite" });
        if (perm === "granted") {
          dirRef.current = handle;
          setFolderName(handle.name);
        }
      } catch { /* handle may be stale */ }
    });
  }, []);

  // Returns the ready handle — picks a new folder if necessary
  const getDir = useCallback(async (): Promise<FileSystemDirectoryHandle | null> => {
    if (dirRef.current) {
      try {
        const perm = await (dirRef.current as any).queryPermission({ mode: "readwrite" });
        if (perm === "granted") return dirRef.current;
        const reperm = await (dirRef.current as any).requestPermission({ mode: "readwrite" });
        if (reperm === "granted") return dirRef.current;
      } catch { /* fall through to picker */ }
    }
    if (!fsa.showDirectoryPicker) {
      // Fallback: browser doesn't support File System Access API
      return null;
    }
    try {
      const handle: FileSystemDirectoryHandle = await fsa.showDirectoryPicker({
        mode: "readwrite",
        startIn: "downloads",
        id: "ocr-images",
      });
      dirRef.current = handle;
      setFolderName(handle.name);
      await idbSet(IDB_KEY, handle);
      return handle;
    } catch { return null; } // user cancelled
  }, []);

  const changeFolder = useCallback(async () => {
    dirRef.current = null;
    setFolderName(null);
    await idbSet(IDB_KEY, null);
    await getDir();
  }, [getDir]);

  // Save image blob immediately, then optionally a JSON sidecar with the OCR result
  const saveImage = useCallback(async (blob: Blob, basename: string): Promise<void> => {
    const dir = await getDir();
    if (!dir) return;
    const fh = await dir.getFileHandle(`${basename}.jpg`, { create: true });
    const w  = await fh.createWritable();
    await w.write(blob);
    await w.close();
  }, [getDir]);

  const saveOcrResult = useCallback(async (
    result: OcrScanResult,
    basename: string,
    scanType: "serial_number" | "melt_number",
  ): Promise<void> => {
    const dir = await getDir();
    if (!dir) return;
    const payload = {
      timestamp:  new Date().toISOString(),
      scan_type:  scanType,
      image_file: `${basename}.jpg`,
      ocr_result: {
        value:              result.value,
        raw_text:           result.raw_text,
        confidence:         result.confidence,
        provider:           result.provider,
        scan_id:            result.scan_id,
        processing_time_ms: result.processing_time_ms ?? null,
      },
    };
    const fh = await dir.getFileHandle(`${basename}.json`, { create: true });
    const w  = await fh.createWritable();
    await w.write(JSON.stringify(payload, null, 2));
    await w.close();
  }, [getDir]);

  return { folderName, saveImage, saveOcrResult, changeFolder };
}

// ─── Camera modal ─────────────────────────────────────────────────────────────

function CameraModal({
  open,
  fieldLabel,
  onCapture,
  onClose,
}: {
  open: boolean;
  fieldLabel: string;
  onCapture: (file: File, blob: Blob) => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [camError, setCamError] = useState<string | null>(null);
  const [captured, setCaptured] = useState<{ blob: Blob; url: string } | null>(null);

  const startCamera = useCallback(() => {
    setCamError(null);
    setReady(false);
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false })
      .then((stream) => {
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.onloadedmetadata = () => setReady(true);
        }
      })
      .catch((err: DOMException) => {
        setCamError(
          err.name === "NotAllowedError"
            ? "Camera permission denied. Please allow camera access in your browser settings."
            : `Could not start camera: ${err.message}`
        );
      });
  }, []);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    if (!open) return;
    setCaptured(null);
    startCamera();
    return stopCamera;
  }, [open, startCamera, stopCamera]);

  const handleCapture = useCallback(() => {
    const video = videoRef.current;
    if (!video || !ready) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      stopCamera();
      setCaptured({ blob, url: URL.createObjectURL(blob) });
    }, "image/jpeg", 0.92);
  }, [ready, stopCamera]);

  const handleRetake = useCallback(() => {
    setCaptured(null);
    startCamera();
  }, [startCamera]);

  const handleUse = useCallback(() => {
    if (!captured) return;
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const safeName = fieldLabel.toLowerCase().replace(/\s+/g, "-");
    const file = new File([captured.blob], `ocr-${safeName}-${ts}.jpg`, { type: "image/jpeg" });
    onCapture(file, captured.blob);
    onClose();
  }, [captured, fieldLabel, onCapture, onClose]);

  const handleClose = useCallback(() => {
    stopCamera();
    setCaptured(null);
    setReady(false);
    onClose();
  }, [stopCamera, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm">
      <div className="relative bg-white dark:bg-slate-800 rounded-2xl shadow-2xl p-4 w-full max-w-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-2">
            <Camera className="w-4 h-4 text-orange-500" />
            Capture — {fieldLabel}
          </h3>
          <button
            onClick={handleClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Error */}
        {camError && (
          <div className="mb-3 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700/50 text-sm text-red-600 dark:text-red-400 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {camError}
          </div>
        )}

        {/* Video or captured preview */}
        <div className="relative bg-black rounded-xl overflow-hidden" style={{ aspectRatio: "16/9" }}>
          {!captured ? (
            <>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover"
              />
              {!ready && !camError && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <Loader2 className="w-8 h-8 text-white animate-spin" />
                </div>
              )}
            </>
          ) : (
            <img src={captured.url} alt="Captured" className="w-full h-full object-cover" />
          )}
        </div>

        {/* Actions */}
        <div className="flex justify-center gap-3 mt-4">
          {!captured ? (
            <Button
              type="button"
              onClick={handleCapture}
              disabled={!ready || !!camError}
              className="bg-orange-500 hover:bg-orange-600 text-white px-10"
            >
              <Camera className="w-4 h-4" />
              Capture
            </Button>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={handleRetake}
                className="border-2 border-slate-300 dark:border-slate-600"
              >
                <RefreshCw className="w-4 h-4" />
                Retake
              </Button>
              <Button
                type="button"
                onClick={handleUse}
                className="bg-emerald-500 hover:bg-emerald-600 text-white px-10"
              >
                <Check className="w-4 h-4" />
                Use Photo
              </Button>
            </>
          )}
        </div>

        <p className="text-center text-xs text-slate-400 dark:text-slate-500 mt-2">
          Photo + OCR result will be saved to your selected folder
        </p>
      </div>
    </div>
  );
}

// ─── HH:MM:SS validator ───────────────────────────────────────────────────────

const hhmmssRegex = /^\d{1,5}:[0-5]\d:[0-5]\d$/;
const hoursField = z
  .string()
  .regex(hhmmssRegex, "Format must be HH:MM:SS (e.g. 1500:30:00)");

// ─── Schema ───────────────────────────────────────────────────────────────────

const step1Schema = z.object({
  batch_number: z.string().optional(),
  serial_number: z.string().min(1, "Serial number is required").toUpperCase(),
  melt_number: z.string().min(1, "Melt number is required"),
  work_order_number: z.string().min(1, "Work order number is required"),
  shop_order_number: z.string().min(1, "Shop order number is required"),
  part_number: z.string().min(1, "Part number is required"),
  nomenclature: z.string().min(1, "Nomenclature is required"),
  engine_number: z.string().optional(),
  engine_hours: hoursField,
  component_hours: z.string().optional().refine(
    (v) => !v || hhmmssRegex.test(v),
    { message: "Format must be HH:MM:SS (e.g. 1500:30:00)" }
  ),
  blade_type: z.enum(["LPTR", "HPTR"]).default("LPTR"),
});

const step2Schema = z.object({
  weight_grams: z.preprocess(Number, z.number().positive("Weight must be positive")),
  static_moment_gcm: z.preprocess(Number, z.number().nonnegative("Must be ≥ 0")),
  height_positions: z.array(z.preprocess(Number, z.number())).optional(),
  height_values_mm: z.array(z.preprocess(Number, z.number())).optional(),
  notes: z.string().optional(),
});

const fullSchema = step1Schema.merge(step2Schema);
type FormValues = z.infer<typeof fullSchema>;

// ─── Step indicator ───────────────────────────────────────────────────────────

const STEPS = [
  { id: 1, label: "Blade Identity", icon: ClipboardList },
  { id: 2, label: "Measurements", icon: Ruler },
  { id: 3, label: "Review & Submit", icon: Eye },
];

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-0">
      {STEPS.map((step, idx) => {
        const Icon = step.icon;
        const done = step.id < current;
        const active = step.id === current;
        return (
          <div key={step.id} className="flex items-center">
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  "w-10 h-10 rounded-full flex items-center justify-center border-2 transition-colors",
                  done
                    ? "bg-emerald-500 border-emerald-500 text-white"
                    : active
                    ? "bg-orange-500 border-orange-500 text-white"
                    : "bg-slate-100 dark:bg-slate-700 border-slate-300 dark:border-slate-600 text-slate-500 dark:text-slate-400"
                )}
              >
                {done ? <Check className="w-5 h-5" /> : <Icon className="w-4 h-4" />}
              </div>
              <span
                className={cn(
                  "text-xs mt-1.5 font-medium whitespace-nowrap",
                  active
                    ? "text-orange-500 dark:text-orange-400"
                    : done
                    ? "text-emerald-500 dark:text-emerald-400"
                    : "text-slate-400 dark:text-slate-500"
                )}
              >
                {step.label}
              </span>
            </div>
            {idx < STEPS.length - 1 && (
              <div
                className={cn(
                  "w-24 h-0.5 mb-5 mx-2",
                  done ? "bg-emerald-500" : "bg-slate-200 dark:bg-slate-700"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function FieldRow({
  label,
  children,
  error,
  required,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  error?: string | undefined;
  required?: boolean | undefined;
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

function OcrButton({ onClick, scanning }: { onClick: () => void; scanning?: boolean }) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={onClick}
      disabled={scanning}
      className="shrink-0 border-2 border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
    >
      {scanning ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : (
        <Camera className="w-4 h-4" />
      )}
      {scanning ? "Scanning…" : "Scan"}
    </Button>
  );
}

function ScanResult({
  scan,
  onUse,
  onDismiss,
}: {
  scan: ScanState;
  onUse: (value: string) => void;
  onDismiss: () => void;
}) {
  if (!scan.result) return null;
  const confidencePct = Math.round((scan.result.confidence ?? 0) * 100);
  const confidenceColor =
    confidencePct >= 85 ? "text-emerald-600 dark:text-emerald-400" :
    confidencePct >= 60 ? "text-amber-600 dark:text-amber-400" :
    "text-red-500 dark:text-red-400";

  return (
    <div className="mt-2 flex items-start gap-3 p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60">
      {scan.preview && (
        <img
          src={scan.preview}
          alt="OCR scan"
          className="w-16 h-16 object-cover rounded-lg border border-slate-200 dark:border-slate-700 shrink-0"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <Camera className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-xs text-slate-500 dark:text-slate-400">OCR detected</span>
          <span className={cn("text-xs font-semibold", confidenceColor)}>{confidencePct}% confidence</span>
        </div>
        <p className="text-sm font-mono font-semibold text-slate-900 dark:text-white truncate">
          {scan.result.value}
        </p>
        {scan.result.error && (
          <p className="text-xs text-red-500 mt-0.5">{scan.result.error}</p>
        )}
      </div>
      <div className="flex flex-col gap-1.5 shrink-0">
        {!scan.applied && (
          <Button
            type="button"
            size="sm"
            onClick={() => onUse(scan.result!.value)}
            className="bg-emerald-500 hover:bg-emerald-600 text-white text-xs h-7 px-2"
          >
            <Check className="w-3 h-3" />
            Use
          </Button>
        )}
        {scan.applied && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
            <Check className="w-3 h-3" /> Applied
          </span>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onDismiss}
          className="text-slate-400 hover:text-slate-600 text-xs h-7 px-2"
        >
          <X className="w-3 h-3" />
        </Button>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function BladeEntryPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [serialUnique, setSerialUnique] = useState<boolean | null>(null);
  const [checkingSerial, setCheckingSerial] = useState(false);
  const [bladeType, setBladeType] = useState<"LPTR" | "HPTR">("LPTR");
  const [batchAutoFilled, setBatchAutoFilled] = useState(false);
  const [batchLookupPending, setBatchLookupPending] = useState(false);
  const [autoFilledFields, setAutoFilledFields] = useState<Set<string>>(new Set());
  const batchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // OCR scan states
  const { folderName, saveImage, saveOcrResult, changeFolder } = useOcrFolder();

  const [serialScan, setSerialScan] = useState<ScanState>(EMPTY_SCAN);
  const [meltScan, setMeltScan] = useState<ScanState>(EMPTY_SCAN);
  const [serialCameraOpen, setSerialCameraOpen] = useState(false);
  const [meltCameraOpen, setMeltCameraOpen] = useState(false);

  const handleSerialCapture = async (file: File, blob: Blob) => {
    const preview = URL.createObjectURL(blob);
    const basename = `ocr-serial-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}`;
    setSerialScan({ scanning: true, result: null, preview, applied: false });
    saveImage(blob, basename); // save JPG immediately, fire-and-forget
    try {
      const result = await ocrService.scanSerial(file);
      setSerialScan({ scanning: false, result, preview, applied: false });
      saveOcrResult(result, basename, "serial_number"); // save JSON sidecar
    } catch {
      setSerialScan({ scanning: false, result: null, preview: null, applied: false });
    }
  };

  const handleMeltCapture = async (file: File, blob: Blob) => {
    const preview = URL.createObjectURL(blob);
    const basename = `ocr-melt-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}`;
    setMeltScan({ scanning: true, result: null, preview, applied: false });
    saveImage(blob, basename);
    try {
      const result = await ocrService.scanMelt(file);
      setMeltScan({ scanning: false, result, preview, applied: false });
      saveOcrResult(result, basename, "melt_number");
    } catch {
      setMeltScan({ scanning: false, result: null, preview: null, applied: false });
    }
  };

  const [heightRows, setHeightRows] = useState<{ pos: number; val: number }[]>([
    { pos: 1, val: 0 },
    { pos: 2, val: 0 },
    { pos: 3, val: 0 },
  ]);

  const {
    register,
    handleSubmit,
    getValues,
    setValue,
    watch,
    trigger,
    setError,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(fullSchema),
    defaultValues: {
      height_positions: [1, 2, 3],
      height_values_mm: [0, 0, 0],
      blade_type: "LPTR",
    },
    mode: "onTouched",
  });

  // ── Weighing machine ──────────────────────────────────────────────────────
  const [rawWeight, setRawWeight] = useState("");

  const applyWeight = useCallback((kg: number) => {
    const raw = kg.toFixed(2);
    setRawWeight(raw);
    const wg = parseFloat((kg * 1.57).toFixed(2));
    const sm = parseFloat((wg * 20).toFixed(2));
    setValue("weight_grams", wg as never, { shouldValidate: true });
    setValue("static_moment_gcm", sm as never, { shouldValidate: true });
  }, [setValue]);

  const { status: scaleStatus, locked: scaleLocked, toggleLock } = useWeighingScale(applyWeight);

  // ── DTI gauge ─────────────────────────────────────────────────────────────
  const [dtiStation, setDtiStation] = useState<string>(
    () => localStorage.getItem("dti_station") ?? "1"
  );
  const { lastReading: dtiReading, connected: dtiConn } = useDTISocket(dtiStation);

  // Which row is receiving live gauge readings (null = all locked / gauge off)
  const [activeRowIdx, setActiveRowIdx] = useState<number | null>(0);
  // Per-row locked state — locked rows are frozen and won't be overwritten by gauge
  const [lockedRows, setLockedRows] = useState<boolean[]>(() => heightRows.map(() => false));

  // Fill the active row with the latest gauge reading (if not locked)
  useEffect(() => {
    if (!dtiReading || activeRowIdx === null) return;
    if (lockedRows[activeRowIdx]) return;
    setHeightRows(rows =>
      rows.map((r, i) => i === activeRowIdx ? { ...r, val: dtiReading.value } : r)
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtiReading]);

  const batchNumber = watch("batch_number");

  // Batch lookup — debounced API call to PostgreSQL batch_groups table
  useEffect(() => {
    const key = batchNumber?.trim() ?? "";
    if (!key) {
      setBatchAutoFilled(false);
      setAutoFilledFields(new Set());
      return;
    }
    if (batchDebounceRef.current) clearTimeout(batchDebounceRef.current);
    batchDebounceRef.current = setTimeout(async () => {
      setBatchLookupPending(true);
      try {
        const result = await bladeService.batchLookup(key);
        if (result.found) {
          const filled = new Set<string>();
          if (result.work_order_number) { setValue("work_order_number", result.work_order_number); filled.add("work_order_number"); }
          if (result.part_number)       { setValue("part_number",       result.part_number!);      filled.add("part_number"); }
          if (result.engine_number)     { setValue("engine_number",     result.engine_number!);    filled.add("engine_number"); }
          if (result.nomenclature)      { setValue("nomenclature",      result.nomenclature!);     filled.add("nomenclature"); }
          setBatchAutoFilled(true);
          setAutoFilledFields(filled);
        } else {
          setBatchAutoFilled(false);
          setAutoFilledFields(new Set());
        }
      } catch {
        /* silent */
      } finally {
        setBatchLookupPending(false);
      }
    }, 500);
    return () => { if (batchDebounceRef.current) clearTimeout(batchDebounceRef.current); };
  }, [batchNumber, setValue]);

  const createMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const engineHours = values.engine_hours;
      const componentHours = values.component_hours?.trim() || engineHours;

      const blade = await bladeService.create({
        serial_number: values.serial_number,
        melt_number: values.melt_number,
        work_order_number: values.work_order_number,
        shop_order_number: values.shop_order_number,
        part_number: values.part_number,
        nomenclature: values.nomenclature,
        blade_type: bladeType,
        ...(values.batch_number ? { batch_number: values.batch_number } : {}),
        ...(values.engine_number ? { engine_number: values.engine_number } : {}),
        ...(engineHours ? { engine_hours: engineHours } : {}),
        ...(componentHours ? { component_hours: componentHours } : {}),
      });

      await bladeService.recordMeasurements(blade.id, {
        measurement_type: "INITIAL",
        weight_grams: values.weight_grams,
        static_moment_gcm: values.static_moment_gcm,
        height_data: (() => {
          const filled = heightRows.filter((r) => r.val !== 0 && r.val != null);
          if (filled.length === 0) return undefined;
          return Object.fromEntries(heightRows.map((r, i) => [`H${i + 1}`, r.val]));
        })(),
        ...(values.notes ? { notes: values.notes } : {}),
      });

      // Attach OCR scan images to the blade (non-blocking on failure)
      if (serialScan.result?.scan_id) {
        await bladeService.attachOcrScan(blade.id, serialScan.result.scan_id, "serial_number").catch(() => {});
      }
      if (meltScan.result?.scan_id) {
        await bladeService.attachOcrScan(blade.id, meltScan.result.scan_id, "melt_number").catch(() => {});
      }

      return blade;
    },
    onSuccess: (blade) => {
      const batchNo = getValues("batch_number")?.trim();
      if (batchNo) {
        bladeService.saveBatchGroup({
          batch_number:      batchNo,
          work_order_number: getValues("work_order_number") ?? "",
          part_number:       getValues("part_number")       ?? "",
          engine_number:     getValues("engine_number")     ?? "",
          nomenclature:      getValues("nomenclature")      ?? "",
        }).catch(() => { /* non-critical */ });
      }
      navigate(`/blades/${blade.id}`);
    },
  });

  const checkSerial = async () => {
    const serial = getValues("serial_number");
    if (!serial) return;
    setCheckingSerial(true);
    const unique = await bladeService.checkSerialUnique(serial);
    setSerialUnique(unique);
    setCheckingSerial(false);
  };

  const goNext = async () => {
    const step1Fields: (keyof FormValues)[] = [
      "serial_number",
      "melt_number",
      "work_order_number",
      "shop_order_number",
      "part_number",
      "nomenclature",
      "engine_hours",
    ];
    const step2Fields: (keyof FormValues)[] = [
      "weight_grams",
      "static_moment_gcm",
    ];
    const valid = await trigger(step === 1 ? step1Fields : step2Fields);

    if (valid && step === 1) {
      const serial = getValues("serial_number");
      if (serial && serialUnique === null) await checkSerial();
      if (serialUnique === false) {
        setError("serial_number", {
          type: "manual",
          message: `Serial number "${getValues("serial_number")}" already exists in the system`,
        });
        return;
      }
    }

    if (valid) setStep((s) => s + 1);
  };

  const values = getValues();

  const inputCls =
    "bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400";

  const autoFilledInputCls = (field: string) =>
    cn(inputCls, autoFilledFields.has(field) && "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/10");

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">
      {/* Camera modals */}
      <CameraModal
        open={serialCameraOpen}
        fieldLabel="Serial Number"
        onCapture={handleSerialCapture}
        onClose={() => setSerialCameraOpen(false)}
      />
      <CameraModal
        open={meltCameraOpen}
        fieldLabel="Melt Number"
        onCapture={handleMeltCapture}
        onClose={() => setMeltCameraOpen(false)}
      />

      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm">
        <div className="flex items-center justify-between max-w-4xl mx-auto">
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">New Blade Entry</h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">OH Station — Initial intake form</p>
            {/* OCR save folder indicator */}
            <div className="mt-1 flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
              <Camera className="w-3 h-3" />
              {folderName ? (
                <>
                  <span>OCR saves to: <span className="font-medium text-slate-600 dark:text-slate-300">{folderName}</span></span>
                  <button onClick={changeFolder} className="text-orange-500 hover:underline">Change</button>
                </>
              ) : (
                <span>OCR images: folder will be selected on first scan</span>
              )}
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(-1)}
            className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          >
            <ChevronLeft className="w-4 h-4" />
            Back
          </Button>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex justify-center mb-8">
          <StepIndicator current={step} />
        </div>

        {/* Step 1 — Identity */}
        {step === 1 && (
          <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-slate-900 dark:text-white text-lg flex items-center gap-2">
                <ClipboardList className="w-5 h-5 text-orange-500" />
                Blade Identity
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">

              {/* Batch Number — full width row */}
              <FieldRow label="Batch Number">
                <div className="flex gap-2 items-center">
                  <Input
                    className={cn(inputCls, "max-w-xs")}
                    {...register("batch_number")}
                  />
                  {batchLookupPending && (
                    <Loader2 className="w-4 h-4 animate-spin text-slate-400 shrink-0" />
                  )}
                  {batchAutoFilled && !batchLookupPending && (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-700/50 rounded-full px-2 py-0.5">
                      <Sparkles className="w-3 h-3" />
                      Auto-filled from previous batch
                    </span>
                  )}
                </div>
                {batchAutoFilled && (
                  <p className="text-xs text-slate-400 dark:text-slate-500 mt-1 flex items-center gap-1">
                    <Pencil className="w-3 h-3" />
                    Fields highlighted in green were auto-filled — you can still edit them.
                  </p>
                )}
              </FieldRow>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                {/* Serial Number */}
                <FieldRow
                  label="Serial Number"
                  error={
                    errors.serial_number?.message ??
                    (serialUnique === false ? "Serial number already exists" : undefined)
                  }
                  required
                >
                  <div className="flex gap-2 items-center">
                    <Input
                      className={cn(inputCls, "uppercase")}
                      {...register("serial_number")}
                      onBlur={checkSerial}
                    />
                    <OcrButton
                      scanning={serialScan.scanning}
                      onClick={() => setSerialCameraOpen(true)}
                    />
                    {checkingSerial && (
                      <Loader2 className="w-4 h-4 animate-spin text-slate-500 dark:text-slate-400 shrink-0" />
                    )}
                    {serialUnique === true && !serialScan.scanning && (
                      <Check className="w-4 h-4 text-emerald-500 shrink-0" />
                    )}
                  </div>
                  <ScanResult
                    scan={serialScan}
                    onUse={(v) => {
                      setValue("serial_number", v.toUpperCase(), { shouldValidate: true });
                      setSerialScan((s) => ({ ...s, applied: true }));
                    }}
                    onDismiss={() => setSerialScan(EMPTY_SCAN)}
                  />
                </FieldRow>

                {/* Melt Number */}
                <FieldRow label="Melt Number" error={errors.melt_number?.message} required>
                  <div className="flex gap-2">
                    <Input className={inputCls} {...register("melt_number")} />
                    <OcrButton
                      scanning={meltScan.scanning}
                      onClick={() => setMeltCameraOpen(true)}
                    />
                  </div>
                  <ScanResult
                    scan={meltScan}
                    onUse={(v) => {
                      setValue("melt_number", v, { shouldValidate: true });
                      setMeltScan((s) => ({ ...s, applied: true }));
                    }}
                    onDismiss={() => setMeltScan(EMPTY_SCAN)}
                  />
                </FieldRow>

                {/* Work Order Number */}
                <FieldRow label="Work Order Number" error={errors.work_order_number?.message} required>
                  <Input className={autoFilledInputCls("work_order_number")} {...register("work_order_number")} />
                </FieldRow>

                {/* Shop Order Number */}
                <FieldRow label="Shop Order Number" error={errors.shop_order_number?.message} required>
                  <Input className={inputCls} {...register("shop_order_number")} />
                </FieldRow>

                {/* Part Number */}
                <FieldRow label="Part Number" error={errors.part_number?.message} required>
                  <Input className={autoFilledInputCls("part_number")} {...register("part_number")} />
                </FieldRow>

                {/* Nomenclature */}
                <FieldRow label="Nomenclature" error={errors.nomenclature?.message} required>
                  <Input className={autoFilledInputCls("nomenclature")} {...register("nomenclature")} />
                </FieldRow>

                {/* Blade type — LPTR vs HPTR */}
                <FieldRow label="Blade Type" required>
                  <div className="grid grid-cols-2 gap-2">
                    {(["LPTR", "HPTR"] as const).map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setBladeType(t)}
                        className={cn(
                          "rounded-xl border-2 py-3 px-4 text-sm font-semibold transition-all",
                          bladeType === t
                            ? "border-orange-500 bg-orange-500 text-white shadow-md"
                            : "border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-700/50 hover:border-orange-400"
                        )}
                      >
                        <span className="block text-base font-bold">{t}</span>
                        <span className="block text-xs font-normal mt-0.5 opacity-80">
                          {t === "LPTR" ? "Rocking + Creep tests" : "Rocking only"}
                        </span>
                      </button>
                    ))}
                  </div>
                  <input type="hidden" {...register("blade_type")} value={bladeType} />
                </FieldRow>

                {/* Engine Number */}
                <FieldRow label="Engine Number" error={errors.engine_number?.message}>
                  <Input className={autoFilledInputCls("engine_number")} {...register("engine_number")} />
                </FieldRow>

                {/* Engine Hours */}
                <FieldRow label="Engine Hours" error={errors.engine_hours?.message} required>
                  <Input
                    placeholder="HH:MM:SS"
                    className={inputCls}
                    {...register("engine_hours")}
                  />
                </FieldRow>

                {/* Component Hours */}
                <FieldRow
                  label="Component Hours"
                  error={errors.component_hours?.message}
                >
                  <Input
                    placeholder="HH:MM:SS (leave blank to copy Engine Hours)"
                    className={inputCls}
                    {...register("component_hours")}
                  />
                </FieldRow>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 2 — Measurements */}
        {step === 2 && (
          <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-slate-900 dark:text-white text-lg flex items-center gap-2">
                <Ruler className="w-5 h-5 text-orange-500" />
                Measurements
                {bladeType === "HPTR" && (
                  <span className="ml-2 text-xs font-normal bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 border border-orange-200 dark:border-orange-700/50 rounded-full px-2 py-0.5">
                    HPTR — Rocking only
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 gap-5">
                {/* Raw weight input — drives auto-fill, live from scale */}
                <FieldRow
                  label={
                    <span className="inline-flex items-center gap-2">
                      Weight
                      {scaleStatus === "connected" && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                          <Wifi className="w-3 h-3" />
                          Live
                        </span>
                      )}
                      {scaleStatus === "connecting" && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-500">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          Connecting…
                        </span>
                      )}
                      {scaleStatus === "disconnected" && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400">
                          <WifiOff className="w-3 h-3" />
                          Scale offline
                        </span>
                      )}
                    </span>
                  }
                  required
                >
                  <div className="flex gap-2 items-center">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      placeholder="0.00"
                      value={rawWeight}
                      readOnly={scaleLocked && scaleStatus === "connected"}
                      onChange={(e) => {
                        if (scaleLocked && scaleStatus === "connected") return;
                        const raw = e.target.value;
                        setRawWeight(raw);
                        const num = parseFloat(raw);
                        if (!isNaN(num) && num > 0) {
                          const wg = parseFloat((num * 1.57).toFixed(2));
                          const sm = parseFloat((wg * 20).toFixed(2));
                          setValue("weight_grams", wg as any, { shouldValidate: true });
                          setValue("static_moment_gcm", sm as any, { shouldValidate: true });
                        }
                      }}
                      className={cn(
                        inputCls,
                        scaleStatus === "connected" && !scaleLocked &&
                          "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/10",
                        scaleLocked && scaleStatus === "connected" &&
                          "border-amber-400 bg-amber-50/40 dark:bg-amber-900/10"
                      )}
                    />
                    {scaleStatus === "connected" && (
                      <button
                        type="button"
                        title={scaleLocked ? "Unlock: resume live weight" : "Lock: freeze this reading"}
                        onClick={toggleLock}
                        className={cn(
                          "flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-lg border-2 transition-colors",
                          scaleLocked
                            ? "border-amber-400 bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400"
                            : "border-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400"
                        )}
                      >
                        {scaleLocked ? <Lock className="w-4 h-4" /> : <Unlock className="w-4 h-4" />}
                      </button>
                    )}
                  </div>
                  {scaleStatus === "connected" && !scaleLocked && rawWeight && Number(rawWeight) > 0 && (
                    <p className="mt-0.5 text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                      <Scale className="w-3 h-3" />
                      Reading live from scale — click <Lock className="w-3 h-3 inline" /> to lock
                    </p>
                  )}
                  {scaleStatus === "connected" && scaleLocked && (
                    <p className="mt-0.5 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
                      <Lock className="w-3 h-3" />
                      Locked at {rawWeight} kg — click <Unlock className="w-3 h-3 inline" /> to resume live
                    </p>
                  )}
                  {scaleStatus !== "connected" && rawWeight && Number(rawWeight) > 0 && (
                    <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                      Auto-fills Weight (grams) and Static Moment
                    </p>
                  )}
                </FieldRow>

                {/* Weight (grams) — auto-filled: raw × 1.57 */}
                <FieldRow
                  label="Weight (grams)"
                  error={errors.weight_grams?.message?.toString()}
                  required
                >
                  <div className="relative">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      placeholder="0.00"
                      className={cn(
                        inputCls,
                        rawWeight && Number(rawWeight) > 0 &&
                          "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/10"
                      )}
                      {...register("weight_grams")}
                    />
                    {rawWeight && Number(rawWeight) > 0 && (
                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-emerald-600 dark:text-emerald-400 font-semibold pointer-events-none">
                        auto
                      </span>
                    )}
                  </div>
                  {rawWeight && Number(rawWeight) > 0 && (
                    <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                      {rawWeight} × 1.57 = {(Number(rawWeight) * 1.57).toFixed(2)} g
                    </p>
                  )}
                </FieldRow>

                {/* Static Moment — auto-filled: weight_grams × 20 */}
                <FieldRow
                  label="Static Moment (g·cm)"
                  error={errors.static_moment_gcm?.message?.toString()}
                  required
                >
                  <div className="relative">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      placeholder="0.00"
                      className={cn(
                        inputCls,
                        rawWeight && Number(rawWeight) > 0 &&
                          "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/10"
                      )}
                      {...register("static_moment_gcm")}
                    />
                    {rawWeight && Number(rawWeight) > 0 && (
                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-emerald-600 dark:text-emerald-400 font-semibold pointer-events-none">
                        auto
                      </span>
                    )}
                  </div>
                  {rawWeight && Number(rawWeight) > 0 && (
                    <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                      {(Number(rawWeight) * 1.57).toFixed(2)} × 20 = {(Number(rawWeight) * 1.57 * 20).toFixed(2)} g·cm
                    </p>
                  )}
                </FieldRow>

              </div>

              {/* Height data */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium flex items-center gap-2">
                    Height Positions (mm)
                    {dtiConn ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                        <Wifi className="w-3 h-3" />
                        DTI Live
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400">
                        <WifiOff className="w-3 h-3" />
                        DTI offline
                      </span>
                    )}
                  </Label>
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
                      <span>Rig:</span>
                      {["1", "2"].map((s) => (
                        <button
                          key={s}
                          type="button"
                          onClick={() => { setDtiStation(s); localStorage.setItem("dti_station", s); }}
                          className={cn(
                            "px-1.5 py-0.5 rounded font-mono text-xs border transition-colors",
                            dtiStation === s
                              ? "bg-orange-500 border-orange-500 text-white"
                              : "border-slate-300 dark:border-slate-600 hover:border-orange-400"
                          )}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="border-2 border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
                      onClick={() => {
                        setHeightRows((rows) => [
                          ...rows,
                          { pos: (rows[rows.length - 1]?.pos ?? 0) + 1, val: 0 },
                        ]);
                        setLockedRows((prev) => [...prev, false]);
                      }}
                    >
                      <Plus className="w-4 h-4" />
                      Add Position
                    </Button>
                  </div>
                </div>
                <div className="space-y-2">
                  {heightRows.map((row, idx) => {
                    const isActive = dtiConn && activeRowIdx === idx;
                    const isLocked = lockedRows[idx] ?? false;
                    return (
                      <div
                        key={idx}
                        className={cn(
                          "flex items-center gap-3 p-1.5 rounded-lg transition-colors",
                          dtiConn && !isLocked && "cursor-pointer",
                          isActive && !isLocked && "bg-emerald-50/40 dark:bg-emerald-900/10 ring-1 ring-emerald-400",
                          isLocked && dtiConn && "bg-amber-50/30 dark:bg-amber-900/10",
                        )}
                        onClick={() => { if (dtiConn && !isLocked) setActiveRowIdx(idx); }}
                      >
                        <span className="text-slate-500 dark:text-slate-400 text-sm w-20 shrink-0">
                          Position {idx + 1}
                        </span>
                        <Input
                          type="number"
                          value={row.pos}
                          onChange={(e) =>
                            setHeightRows((rows) =>
                              rows.map((r, i) => i === idx ? { ...r, pos: Number(e.target.value) } : r)
                            )
                          }
                          className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white w-32"
                        />
                        <span className="text-slate-500 dark:text-slate-400 text-sm">→</span>
                        <Input
                          type="number"
                          step="0.001"
                          value={row.val}
                          readOnly={isLocked && dtiConn}
                          onChange={(e) =>
                            setHeightRows((rows) =>
                              rows.map((r, i) => i === idx ? { ...r, val: Number(e.target.value) } : r)
                            )
                          }
                          onClick={(e) => { e.stopPropagation(); if (dtiConn && !isLocked) setActiveRowIdx(idx); }}
                          placeholder="Value (mm)"
                          className={cn(
                            "bg-slate-50 dark:bg-slate-700/50 text-slate-900 dark:text-white flex-1 transition-colors",
                            isActive && !isLocked
                              ? "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/10"
                              : isLocked && dtiConn
                              ? "border-amber-400 bg-amber-50/40 dark:bg-amber-900/10"
                              : "border-slate-300 dark:border-slate-600",
                          )}
                        />
                        {dtiConn && (
                          <button
                            type="button"
                            title={isLocked ? "Unlock: resume live reading" : "Lock: freeze this reading"}
                            onClick={(e) => {
                              e.stopPropagation();
                              if (isLocked) {
                                setLockedRows((prev) => { const n = [...prev]; n[idx] = false; return n; });
                                setActiveRowIdx(idx);
                              } else {
                                setLockedRows((prev) => { const n = [...prev]; n[idx] = true; return n; });
                                const next = heightRows.findIndex((_, i) => i > idx && !(lockedRows[i] ?? false));
                                setActiveRowIdx(next === -1 ? null : next);
                              }
                            }}
                            className={cn(
                              "shrink-0 flex items-center justify-center w-9 h-9 rounded-lg border-2 transition-colors",
                              isLocked
                                ? "border-amber-400 bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400"
                                : "border-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400"
                            )}
                          >
                            {isLocked ? <Lock className="w-4 h-4" /> : <Unlock className="w-4 h-4" />}
                          </button>
                        )}
                        {idx > 0 && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            onClick={(e) => {
                              e.stopPropagation();
                              setHeightRows((rows) => rows.filter((_, i) => i !== idx));
                              setLockedRows((prev) => prev.filter((_, i) => i !== idx));
                              setActiveRowIdx((prev) => {
                                if (prev === null) return null;
                                if (prev === idx) return Math.max(0, idx - 1);
                                if (prev > idx) return prev - 1;
                                return prev;
                              });
                            }}
                            className="text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300 hover:bg-red-50 dark:hover:bg-red-500/10"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              <FieldRow label="Inspection Remarks">
                <Textarea
                  placeholder="Enter any inspection notes or observations…"
                  className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white min-h-[100px]"
                  {...register("notes")}
                />
              </FieldRow>
            </CardContent>
          </Card>
        )}

        {/* Step 3 — Review */}
        {step === 3 && (
          <div className="space-y-4">
            <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
              <CardHeader>
                <CardTitle className="text-slate-900 dark:text-white text-base">Blade Identity</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                  {(
                    [
                      ["Batch Number", values.batch_number ?? "—"],
                      ["Serial Number", values.serial_number],
                      ["Melt Number", values.melt_number],
                      ["Work Order", values.work_order_number],
                      ["Shop Order", values.shop_order_number],
                      ["Part Number", values.part_number],
                      ["Nomenclature", values.nomenclature],
                      ["Blade Type", bladeType],
                      ["Engine Number", values.engine_number ?? "—"],
                      ["Engine Hours", values.engine_hours ?? "—"],
                      ["Component Hours", values.component_hours?.trim() || values.engine_hours || "—"],
                    ] as [string, string][]
                  ).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-slate-500 dark:text-slate-400">{k}</dt>
                      <dd className="text-slate-900 dark:text-white font-medium">{v}</dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>

            <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
              <CardHeader>
                <CardTitle className="text-slate-900 dark:text-white text-base">Measurements</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                  {(
                    [
                      ...(rawWeight && Number(rawWeight) > 0
                        ? [["Weight (raw)", rawWeight] as [string, string]]
                        : []),
                      ["Weight (grams)", `${String(values.weight_grams)} g`],
                      ["Static Moment", `${String(values.static_moment_gcm)} g·cm`],
                    ] as [string, string][]
                  ).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-slate-500 dark:text-slate-400">{k}</dt>
                      <dd className="text-slate-900 dark:text-white font-medium">{v}</dd>
                    </div>
                  ))}
                </dl>
                {values.notes && (
                  <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
                    <dt className="text-slate-500 dark:text-slate-400 text-sm mb-1">Remarks</dt>
                    <dd className="text-slate-900 dark:text-white text-sm">{values.notes}</dd>
                  </div>
                )}
              </CardContent>
            </Card>

            {createMutation.isError && (
              <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
                <AlertCircle className="h-4 w-4 text-red-500" />
                <AlertDescription className="text-red-700 dark:text-red-300">
                  {extractApiError(createMutation.error)}
                </AlertDescription>
              </Alert>
            )}
          </div>
        )}

        {/* Navigation */}
        <div className="flex items-center justify-between mt-8">
          <Button
            variant="outline"
            onClick={() => setStep((s) => Math.max(1, s - 1))}
            disabled={step === 1}
            className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
          >
            <ChevronLeft className="w-4 h-4" />
            Previous
          </Button>

          <div className="flex items-center gap-3">
            {step < 3 && (
              <Button type="button" onClick={goNext} className="bg-orange-500 hover:bg-orange-600 text-white">
                Next
                <ChevronRight className="w-4 h-4" />
              </Button>
            )}
            {step === 3 && (
              <Button
                type="button"
                onClick={handleSubmit((v) => createMutation.mutate(v))}
                disabled={createMutation.isPending}
                className="bg-emerald-500 hover:bg-emerald-600 text-white px-10"
              >
                {createMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4" />
                    Save
                  </>
                )}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
