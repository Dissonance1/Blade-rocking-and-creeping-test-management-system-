/**
 * Client for the OAK-1 companion service (scripts/oak1_camera_service.py).
 *
 * The OAK-1 (Luxonis DepthAI) is not a UVC webcam — getUserMedia() cannot see
 * it. The companion service runs standalone on the workstation with the OAK-1
 * plugged in and serves frames over plain localhost HTTP; this client fetches
 * from it directly and hands back a Blob that flows into the exact same
 * upload path as a browser-webcam capture (ocrService / runBackendOCR).
 *
 * OAK-1 is optional/supplemental hardware — every function here must fail
 * quietly so callers can fall back to the existing browser webcam flow
 * instead of breaking it.
 *
 * Note: the frontend is served over https://localhost while this service is
 * plain http://localhost — Chromium treats http://localhost as a secure-
 * context exception, so this isn't blocked as mixed content in Chrome/Edge.
 * Other browsers may block it; not engineered around since this is a
 * shop-floor app on a known browser.
 */

import type { BladeType } from "@/types";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const OAK1_SERVICE_URL: string = (import.meta as any).env?.VITE_OAK1_SERVICE_URL ?? "http://localhost:8089";

const HEALTH_TIMEOUT_MS = 1500;
const SNAPSHOT_TIMEOUT_MS = 3000;

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/** Returns true only if the companion service is reachable AND the OAK-1 is connected. */
export async function checkOak1Health(): Promise<boolean> {
  try {
    const res = await fetchWithTimeout(`${OAK1_SERVICE_URL}/health`, HEALTH_TIMEOUT_MS);
    if (!res.ok) return false;
    const data = (await res.json()) as { connected?: boolean };
    return data.connected === true;
  } catch {
    return false;
  }
}

/**
 * Fetches the latest frame from the OAK-1 as a JPEG Blob. Throws on failure —
 * callers should catch.
 *
 * `bladeType`, when given, is forwarded as `?blade_type=` so the companion
 * service applies that blade type's dialed-in digital zoom/pan (HPTR and
 * LPTR blades differ in size and in where their melt-number stamp sits) —
 * see ZOOM_BY_BLADE_TYPE/PAN_BY_BLADE_TYPE in oak1_camera_service.py.
 */
export async function captureOak1Snapshot(bladeType?: BladeType | null): Promise<Blob> {
  const url = bladeType
    ? `${OAK1_SERVICE_URL}/snapshot?blade_type=${bladeType}`
    : `${OAK1_SERVICE_URL}/snapshot`;
  const res = await fetchWithTimeout(url, SNAPSHOT_TIMEOUT_MS);
  if (!res.ok) {
    throw new Error(`OAK-1 snapshot failed with status ${res.status}`);
  }
  return res.blob();
}

/**
 * URL for the continuous MJPEG live-preview stream — point an <img> at this
 * directly. Deliberately not fetched via JS/blob like captureOak1Snapshot:
 * a plain <img src> lets the browser render the multipart stream natively
 * over one long-lived connection, instead of polling /snapshot on a timer
 * (which caps the preview at 1/interval fps with up to one interval of
 * staleness on top).
 *
 * `bladeType` is forwarded the same way as in captureOak1Snapshot — the
 * live preview should already show the framing the actual capture will use.
 */
export function getOak1StreamUrl(bladeType?: BladeType | null): string {
  return bladeType ? `${OAK1_SERVICE_URL}/stream?blade_type=${bladeType}` : `${OAK1_SERVICE_URL}/stream`;
}
