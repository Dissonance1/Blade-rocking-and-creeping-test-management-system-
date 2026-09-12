/**
 * Client for an optional local OCR companion service
 * (scripts/hptr_ocr_service.py) — runs PaddleOCR on this station's own
 * hardware instead of the central OH backend, so scans from this station
 * don't add to the OH PC's OCR load. Only the small JSON detection result
 * comes back synchronously; the captured image is uploaded to the OH PC in
 * the background afterward by the companion service itself, so the
 * blade-record attachment/audit view and OCR training-dataset export still
 * end up with it — see `image_pending` on `OcrScanResult`.
 *
 * There is exactly one frontend build served to every station (see
 * CLAUDE.md's single-server deployment), so — exactly like oak1Camera.ts —
 * availability can't be a build-time flag: every browser gets the same
 * default `http://localhost:8090`, and whether anything actually answers
 * there depends entirely on which physical machine that browser happens to
 * be running on. `shouldUseLocalOcr()` is a cached runtime health probe for
 * that reason; callers should use it (or `checkLocalOcrHealth()` directly,
 * for a one-shot check like a component mount) rather than assuming this
 * service is or isn't present.
 */

import type { OcrScanResult } from "./ocrService";
import { useAuthStore } from "@/store/authStore";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LOCAL_OCR_SERVICE_URL: string = (import.meta as any).env?.VITE_LOCAL_OCR_SERVICE_URL ?? "http://localhost:8090";

const HEALTH_TIMEOUT_MS = 1500;
// Local PaddleOCR inference (five preprocessing variants x two language
// engines, see paddle_provider.py) can take several seconds on modest
// hardware — well above a normal API timeout.
const SCAN_TIMEOUT_MS = 20_000;
// How long a health-check result is trusted before re-probing. Scans happen
// far more often than the service's availability changes, so this avoids a
// round trip to localhost before every single scan while still noticing
// within half a minute if the companion service goes away or comes up.
const HEALTH_CACHE_MS = 30_000;

export type LocalOcrField = "blade-serial" | "melt-number";

let cachedHealthy: boolean | null = null;
let cachedAt = 0;

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/** Returns true only if the companion service is reachable AND its OCR engine has finished loading. Always re-probes — see `shouldUseLocalOcr` for the cached version most callers want. */
export async function checkLocalOcrHealth(): Promise<boolean> {
  try {
    const res = await fetchWithTimeout(`${LOCAL_OCR_SERVICE_URL}/health`, {}, HEALTH_TIMEOUT_MS);
    if (!res.ok) return false;
    const data = (await res.json()) as { ready?: boolean };
    return data.ready === true;
  } catch {
    return false;
  }
}

/** Cached (`HEALTH_CACHE_MS`) version of `checkLocalOcrHealth` — what scanMelt/runBackendOCR use before every scan so they don't pay a network round trip each time. */
export async function shouldUseLocalOcr(): Promise<boolean> {
  const now = Date.now();
  if (cachedHealthy !== null && now - cachedAt < HEALTH_CACHE_MS) {
    return cachedHealthy;
  }
  cachedHealthy = await checkLocalOcrHealth();
  cachedAt = now;
  return cachedHealthy;
}

/**
 * Sends `file` to the local OCR companion service and returns the same
 * shape the central `/ocr/scan/*` endpoints return, so callers don't need
 * to know which one actually ran. Throws on failure — callers should catch
 * and fall back to the central endpoint.
 */
export async function scanViaLocalOcr(file: File | Blob, field: LocalOcrField): Promise<OcrScanResult> {
  const accessToken = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append("image", file, "scan.jpg");

  const res = await fetchWithTimeout(
    `${LOCAL_OCR_SERVICE_URL}/scan/${field}`,
    {
      method: "POST",
      body: form,
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
    },
    SCAN_TIMEOUT_MS
  );
  if (!res.ok) {
    throw new Error(`Local OCR service responded with ${res.status}`);
  }
  return (await res.json()) as OcrScanResult;
}
