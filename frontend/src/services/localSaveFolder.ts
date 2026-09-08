/**
 * Optional local copy of blade-entry OCR captures. The backend upload
 * (ocrService.scanMelt + attachScan) is always the source of truth — this
 * just mirrors the photo + detection result into a folder on the PC's own
 * disk, so operators don't have to dig through the Docker volume to find a
 * scan.
 *
 * Writes go through the OAK-1 companion service (scripts/oak1_camera_service.py),
 * already running locally on this PC — the folder is chosen once via a native
 * OS dialog on that process, not the browser's File System Access API. That
 * API's write-permission grant lapses on every page reload and has to be
 * re-approved by a click; routing through the local service avoids that
 * entirely; once chosen, it stays chosen.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const OAK1_SERVICE_URL: string = (import.meta as any).env?.VITE_OAK1_SERVICE_URL ?? "http://localhost:8089";

const REQUEST_TIMEOUT_MS = 3000;
const CHOOSE_TIMEOUT_MS = 120_000; // the native dialog waits on the operator

export interface OcrCaptureForSave {
  value: string;
  confidence: number;
  raw_text: string;
  provider: string;
  scan_id: string;
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export interface SaveFolderInfo {
  path: string | null;
  name: string | null;
}

/** Reachability + current folder in one call — throws if the service is unreachable. */
export async function getSaveFolder(): Promise<SaveFolderInfo> {
  const res = await fetchWithTimeout(`${OAK1_SERVICE_URL}/save-folder`, {}, REQUEST_TIMEOUT_MS);
  if (!res.ok) throw new Error(`save-folder check failed with status ${res.status}`);
  return res.json();
}

/** Opens a native folder-picker dialog on the PC running the companion service. Throws if cancelled or unreachable. */
export async function chooseSaveFolder(): Promise<SaveFolderInfo> {
  const res = await fetchWithTimeout(`${OAK1_SERVICE_URL}/save-folder/choose`, { method: "POST" }, CHOOSE_TIMEOUT_MS);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `choose folder failed with status ${res.status}`);
  }
  return res.json();
}

export async function forgetSaveFolder(): Promise<void> {
  await fetchWithTimeout(`${OAK1_SERVICE_URL}/save-folder`, { method: "DELETE" }, REQUEST_TIMEOUT_MS);
}

/** Writes `<name>.jpg` + `<name>.json` (the OCR detection) into the configured folder.
 * Returns false (rather than throwing) when no folder is configured yet or the
 * companion service is unreachable — callers should surface that instead of
 * assuming a silent no-op means saved. */
export async function saveCaptureToFolder(opts: {
  workOrderNumber: string;
  fieldLabel: string;
  photoBlob: Blob;
  ocr: OcrCaptureForSave;
}): Promise<boolean> {
  const form = new FormData();
  form.append("photo", opts.photoBlob, "capture.jpg");
  form.append(
    "meta",
    JSON.stringify({
      work_order_number: opts.workOrderNumber,
      field: opts.fieldLabel,
      ...opts.ocr,
    })
  );

  try {
    const res = await fetchWithTimeout(
      `${OAK1_SERVICE_URL}/save-capture`,
      { method: "POST", body: form },
      REQUEST_TIMEOUT_MS
    );
    return res.ok;
  } catch {
    return false;
  }
}
