/**
 * CameraScanner — opens the device camera, lets the operator capture a frame,
 * and sends it to the backend OCR / QR endpoint.
 *
 * Modes:
 *   "qr"     → POST /ocr/scan/qr       (tries BarcodeDetector first, then backend)
 *   "serial" → POST /ocr/scan/blade-serial
 *   "melt"   → POST /ocr/scan/melt-number
 */

import { useRef, useState, useEffect, useCallback } from "react";
import {
  Camera,
  X,
  ZapOff,
  Zap,
  Loader2,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import api from "@/services/api";

export type ScanMode = "qr" | "serial" | "melt";

interface ScanResult {
  value: string;
  confidence?: number;
  provider?: string;
}

interface CameraScannerProps {
  mode: ScanMode;
  onResult: (value: string) => void;
  onClose: () => void;
}

const MODE_LABELS: Record<ScanMode, string> = {
  qr: "QR Code",
  serial: "Blade Serial Number",
  melt: "Melt Number",
};

const MODE_HINTS: Record<ScanMode, string> = {
  qr: "Point the camera at the QR code on the blade tag",
  serial: "Frame the blade serial number clearly in the camera view",
  melt: "Frame the melt / heat number stamp clearly in the camera view",
};

// ─── BarcodeDetector (Chrome/Edge native QR decoding) ────────────────────────

declare global {
  interface Window {
    BarcodeDetector?: new (opts: { formats: string[] }) => {
      detect: (image: HTMLVideoElement | HTMLCanvasElement) => Promise<{ rawValue: string }[]>;
    };
  }
}

function hasBarcodeDetector(): boolean {
  return typeof window !== "undefined" && "BarcodeDetector" in window;
}

// ─── Post image blob to backend OCR endpoint ─────────────────────────────────

async function runBackendOCR(blob: Blob, mode: ScanMode): Promise<ScanResult> {
  const form = new FormData();
  form.append("image", blob, "scan.jpg");

  const endpoint =
    mode === "qr"
      ? "/ocr/scan/qr"
      : mode === "melt"
      ? "/ocr/scan/melt-number"
      : "/ocr/scan/blade-serial";

  const { data } = await api.post<{
    value?: string;
    raw_text?: string;
    confidence?: number;
    provider?: string;
    structured_data?: { data?: string; value?: string };
  }>(endpoint, form, { headers: { "Content-Type": "multipart/form-data" } });

  const value =
    data.structured_data?.data ??
    data.structured_data?.value ??
    data.value ??
    data.raw_text ??
    "";

  return {
    value,
    confidence: data.confidence,
    provider: data.provider,
  };
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function CameraScanner({ mode, onResult, onClose }: CameraScannerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const detectorRef = useRef<InstanceType<NonNullable<typeof window.BarcodeDetector>> | null>(null);

  const [phase, setPhase] = useState<"starting" | "live" | "captured" | "processing" | "error">("starting");
  const [errorMsg, setErrorMsg] = useState("");
  const [capturedSrc, setCapturedSrc] = useState<string | null>(null);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [autoScanActive, setAutoScanActive] = useState(mode === "qr");

  // ── Start camera ────────────────────────────────────────────────────────────
  const startCamera = useCallback(async () => {
    setPhase("starting");
    setErrorMsg("");
    setScanResult(null);
    setCapturedSrc(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setPhase("live");

      // Init BarcodeDetector for QR auto-scan
      if (mode === "qr" && hasBarcodeDetector() && window.BarcodeDetector) {
        detectorRef.current = new window.BarcodeDetector({ formats: ["qr_code", "code_128", "ean_13", "data_matrix"] });
      }
    } catch (e) {
      setErrorMsg(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Camera permission denied. Allow camera access and try again."
          : "Could not open camera. Check that a camera is connected and try again."
      );
      setPhase("error");
    }
  }, [mode]);

  useEffect(() => {
    startCamera();
    return () => {
      cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, [startCamera]);

  // ── Auto QR scan loop (BarcodeDetector) ────────────────────────────────────
  useEffect(() => {
    if (phase !== "live" || mode !== "qr" || !autoScanActive || !detectorRef.current) return;

    let stopped = false;

    const tick = async () => {
      if (stopped || !videoRef.current || !detectorRef.current) return;
      try {
        const barcodes = await detectorRef.current.detect(videoRef.current);
        if (barcodes.length > 0 && barcodes[0]) {
          const value = barcodes[0].rawValue;
          onResult(value);
          onClose();
          return;
        }
      } catch {
        // detection frame error — keep looping
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      stopped = true;
      cancelAnimationFrame(rafRef.current);
    };
  }, [phase, mode, autoScanActive, onResult, onClose]);

  // ── Capture frame ───────────────────────────────────────────────────────────
  const captureFrame = useCallback(async () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);

    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    setCapturedSrc(dataUrl);
    setPhase("processing");

    // Stop live video while processing
    cancelAnimationFrame(rafRef.current);

    try {
      let result: ScanResult;

      // Try BarcodeDetector first for QR mode
      if (mode === "qr" && detectorRef.current) {
        const barcodes = await detectorRef.current.detect(canvas);
        if (barcodes.length > 0 && barcodes[0]) {
          result = { value: barcodes[0].rawValue, provider: "BarcodeDetector", confidence: 1 };
        } else {
          // Fall back to backend
          const blob = await new Promise<Blob>((res) => canvas.toBlob((b) => res(b!), "image/jpeg", 0.9));
          result = await runBackendOCR(blob, mode);
        }
      } else {
        const blob = await new Promise<Blob>((res) => canvas.toBlob((b) => res(b!), "image/jpeg", 0.9));
        result = await runBackendOCR(blob, mode);
      }

      setScanResult(result);
      setPhase("captured");
    } catch {
      setErrorMsg("Scan failed. Try again with better lighting or a clearer image.");
      setPhase("error");
    }
  }, [mode]);

  // ── Accept result ───────────────────────────────────────────────────────────
  const acceptResult = () => {
    if (scanResult?.value) {
      onResult(scanResult.value);
      onClose();
    }
  };

  // ── Retry ───────────────────────────────────────────────────────────────────
  const retry = () => {
    setCapturedSrc(null);
    setScanResult(null);
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
    setPhase("live");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="relative w-full max-w-md mx-4 bg-slate-900 rounded-2xl shadow-2xl overflow-hidden border border-slate-700">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-slate-800/80 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <Camera className="w-4 h-4 text-orange-400" />
            <span className="text-sm font-semibold text-white">Scan {MODE_LABELS[mode]}</span>
          </div>
          <div className="flex items-center gap-2">
            {mode === "qr" && hasBarcodeDetector() && (
              <button
                onClick={() => setAutoScanActive((p) => !p)}
                className={cn(
                  "flex items-center gap-1 text-xs rounded-full px-2 py-0.5 transition-colors",
                  autoScanActive
                    ? "bg-orange-500/20 text-orange-400"
                    : "bg-slate-700 text-slate-400"
                )}
              >
                {autoScanActive ? <Zap className="w-3 h-3" /> : <ZapOff className="w-3 h-3" />}
                Auto
              </button>
            )}
            <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Camera / preview area */}
        <div className="relative bg-black aspect-video flex items-center justify-center overflow-hidden">
          {/* Live video */}
          <video
            ref={videoRef}
            className={cn("w-full h-full object-cover", (phase === "captured" || phase === "processing") && "hidden")}
            playsInline
            muted
          />

          {/* Captured frame preview */}
          {capturedSrc && (phase === "captured" || phase === "processing") && (
            <img src={capturedSrc} className="w-full h-full object-cover" alt="Captured frame" />
          )}

          {/* Starting overlay */}
          {phase === "starting" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-slate-400">
              <Loader2 className="w-8 h-8 animate-spin" />
              <span className="text-sm">Starting camera…</span>
            </div>
          )}

          {/* Error overlay */}
          {phase === "error" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center text-red-400">
              <AlertCircle className="w-10 h-10" />
              <p className="text-sm">{errorMsg}</p>
              <button
                onClick={startCamera}
                className="flex items-center gap-1 text-xs bg-slate-700 hover:bg-slate-600 text-white px-3 py-1.5 rounded-lg transition-colors"
              >
                <RefreshCw className="w-3 h-3" /> Retry
              </button>
            </div>
          )}

          {/* Processing overlay */}
          {phase === "processing" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/50">
              <Loader2 className="w-8 h-8 animate-spin text-orange-400" />
              <span className="text-sm text-white">Scanning…</span>
            </div>
          )}

          {/* Auto-scan viewfinder (QR mode) */}
          {phase === "live" && mode === "qr" && autoScanActive && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="w-52 h-52 relative">
                {/* Corner marks */}
                {[
                  "top-0 left-0 border-t-2 border-l-2 rounded-tl-lg",
                  "top-0 right-0 border-t-2 border-r-2 rounded-tr-lg",
                  "bottom-0 left-0 border-b-2 border-l-2 rounded-bl-lg",
                  "bottom-0 right-0 border-b-2 border-r-2 rounded-br-lg",
                ].map((cls) => (
                  <div key={cls} className={cn("absolute w-6 h-6 border-orange-400", cls)} />
                ))}
                <div className="absolute inset-2 border border-dashed border-white/20 rounded" />
              </div>
            </div>
          )}
        </div>

        {/* Hint text */}
        <div className="px-4 pt-3 pb-1">
          <p className="text-xs text-slate-400 text-center">{MODE_HINTS[mode]}</p>
        </div>

        {/* Result panel */}
        {scanResult && phase === "captured" && (
          <div className="mx-4 mb-2 rounded-lg bg-emerald-900/30 border border-emerald-700 p-3">
            <div className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <p className="text-xs text-emerald-400 font-semibold mb-0.5">Detected</p>
                <p className="text-sm font-mono text-white break-all">{scanResult.value}</p>
                {scanResult.confidence != null && (
                  <p className="text-xs text-slate-400 mt-1">
                    Confidence: {Math.round(scanResult.confidence * 100)}% · Provider: {scanResult.provider}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Hidden canvas for frame capture */}
        <canvas ref={canvasRef} className="hidden" />

        {/* Action buttons */}
        <div className="flex gap-2 px-4 pb-4 pt-2">
          {phase === "live" && (
            <Button
              className="flex-1 bg-orange-500 hover:bg-orange-400 text-white"
              onClick={captureFrame}
            >
              <Camera className="w-4 h-4 mr-2" />
              {mode === "qr" ? "Capture QR" : "Capture & Scan"}
            </Button>
          )}
          {phase === "captured" && scanResult && (
            <>
              <Button variant="outline" className="border-slate-600 text-slate-300 hover:bg-slate-700" onClick={retry}>
                <RefreshCw className="w-4 h-4 mr-1" /> Retry
              </Button>
              <Button className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white" onClick={acceptResult}>
                <CheckCircle2 className="w-4 h-4 mr-1" /> Use This Value
              </Button>
            </>
          )}
          {phase === "captured" && !scanResult && (
            <Button variant="outline" className="flex-1 border-slate-600 text-slate-300 hover:bg-slate-700" onClick={retry}>
              <RefreshCw className="w-4 h-4 mr-1" /> No result — try again
            </Button>
          )}
          {(phase === "starting" || phase === "processing") && (
            <Button disabled className="flex-1 bg-slate-700 text-slate-400">
              <Loader2 className="w-4 h-4 animate-spin mr-2" /> Please wait…
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
