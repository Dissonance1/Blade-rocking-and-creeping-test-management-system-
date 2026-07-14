import { useState, useEffect, useRef, useCallback } from "react";
import { Check, Loader2, AlertCircle, X, Camera, RefreshCw, Cpu, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import { checkOak1Health, captureOak1Snapshot, getOak1StreamUrl } from "@/services/oak1Camera";

type CameraSource = "browser" | "oak1";

/** Auto-capture settle delay (ms) once the feed is ready, before firing the shot. */
const AUTO_CAPTURE_SETTLE_MS = 500;

export default function CameraModal({
  open,
  fieldLabel,
  autoCapture = false,
  onCapture,
  onClose,
}: {
  open: boolean;
  fieldLabel: string;
  /** When true, fires a capture automatically once the feed is ready (no manual button press). */
  autoCapture?: boolean;
  onCapture: (file: File, blob: Blob) => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [camError, setCamError] = useState<string | null>(null);
  const [captured, setCaptured] = useState<{ blob: Blob; url: string } | null>(null);

  // ── OAK-1 companion-service source (optional — falls back to browser webcam) ─
  const [oak1Available, setOak1Available] = useState(false);
  const [source, setSource] = useState<CameraSource | null>(null);

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

  // Resolve which camera source to use each time the modal opens. `source`
  // starts `null` (undecided) so the browser camera isn't opened — and
  // doesn't trigger a permission prompt — before the OAK-1 health check
  // (never throws) has had a chance to prefer it instead.
  useEffect(() => {
    if (!open) {
      setSource(null);
      return undefined;
    }
    let cancelled = false;
    checkOak1Health().then((available) => {
      if (cancelled) return;
      setOak1Available(available);
      setSource(available ? "oak1" : "browser");
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open || source === null) return undefined;
    setCaptured(null);
    if (source === "browser") {
      startCamera();
      return stopCamera;
    }
    // source === "oak1": nothing to open — the companion service already
    // keeps the OAK-1 pipeline running; the <img> stream's onLoad drives `ready`.
    setCamError(null);
    setReady(false);
    return undefined;
  }, [open, source, startCamera, stopCamera]);

  const handleCapture = useCallback(async () => {
    if (!ready) return;

    if (source === "oak1") {
      try {
        const blob = await captureOak1Snapshot();
        setCaptured({ blob, url: URL.createObjectURL(blob) });
      } catch {
        setCamError("Could not capture from OAK-1. Check the companion service and try again.");
      }
      return;
    }

    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      stopCamera();
      setCaptured({ blob, url: URL.createObjectURL(blob) });
    }, "image/jpeg", 0.92);
  }, [ready, stopCamera, source]);

  // Auto-capture: once the feed reports ready, fire the shot after a short
  // settle delay so the operator has a moment to position the blade under
  // the lens. Only applies while nothing has been captured yet.
  useEffect(() => {
    if (!autoCapture || !open || !ready || captured || camError) return undefined;
    const t = setTimeout(() => {
      void handleCapture();
    }, AUTO_CAPTURE_SETTLE_MS);
    return () => clearTimeout(t);
  }, [autoCapture, open, ready, captured, camError, handleCapture]);

  const handleRetake = useCallback(() => {
    setCaptured(null);
    if (source === "browser") startCamera();
    // source === "oak1": clearing `captured` remounts the stream <img> below;
    // reset `ready` so the loading spinner shows until it re-fires onLoad.
    else setReady(false);
  }, [startCamera, source]);

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
    setSource(null);
    onClose();
  }, [stopCamera, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm">
      <div className="relative bg-white dark:bg-background rounded-2xl shadow-2xl p-4 w-full max-w-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 mb-3">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-2 min-w-0 truncate">
            <Camera className="w-4 h-4 text-orange-500 shrink-0" />
            <span className="truncate">Capture — {fieldLabel}</span>
          </h3>
          <div className="flex items-center gap-2 shrink-0">
            {oak1Available && (
              <button
                onClick={() => setSource((p) => (p === "oak1" ? "browser" : "oak1"))}
                title={source === "oak1" ? "Switch to browser camera" : "Switch to OAK-1 industrial camera"}
                className={cn(
                  "flex items-center gap-1 text-xs rounded-full px-2 py-0.5 transition-colors",
                  source === "oak1"
                    ? "bg-orange-100 text-orange-600 dark:bg-orange-500/20 dark:text-orange-400"
                    : "bg-slate-100 text-slate-500 dark:bg-background dark:text-slate-400"
                )}
              >
                {source === "oak1" ? <Cpu className="w-3 h-3" /> : <Video className="w-3 h-3" />}
                {source === "oak1" ? "OAK-1" : "Browser"}
              </button>
            )}
            <button
              onClick={handleClose}
              className="flex items-center justify-center w-11 h-11 -m-2.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
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
              {source === "browser" && (
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-full object-cover"
                />
              )}
              {source === "oak1" && (
                <img
                  src={getOak1StreamUrl()}
                  onLoad={() => setReady(true)}
                  onError={() => setReady(false)}
                  alt="OAK-1 live preview"
                  className="w-full h-full object-cover"
                />
              )}
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
        <div className="flex flex-col sm:flex-row justify-center gap-3 mt-4">
          {!captured ? (
            <Button
              type="button"
              size="lg"
              onClick={handleCapture}
              disabled={!ready || !!camError}
              className="w-full sm:w-auto bg-orange-500 hover:bg-orange-600 text-white px-10"
            >
              <Camera className="w-4 h-4" />
              {autoCapture ? "Capturing…" : "Capture"}
            </Button>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                size="lg"
                onClick={handleRetake}
                className="w-full sm:w-auto border-2 border-slate-300 dark:border-slate-600"
              >
                <RefreshCw className="w-4 h-4" />
                Retake
              </Button>
              <Button
                type="button"
                size="lg"
                onClick={handleUse}
                className="w-full sm:w-auto bg-emerald-500 hover:bg-emerald-600 text-white px-10"
              >
                <Check className="w-4 h-4" />
                Use Photo
              </Button>
            </>
          )}
        </div>

        <p className="text-center text-xs text-slate-400 dark:text-slate-500 mt-2">
          {autoCapture
            ? "Auto-capturing — press Enter/Escape after review to confirm or retake"
            : "Photo + OCR result will be saved to your selected folder"}
        </p>
      </div>
    </div>
  );
}
