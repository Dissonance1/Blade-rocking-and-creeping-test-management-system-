/**
 * Optional local copy of blade-entry OCR captures. The backend upload
 * (ocrService.scanMelt + attachScan) is always the source of truth — this
 * just mirrors the photo + detection result into an operator-chosen folder
 * on the PC's own disk, via the File System Access API, so operators don't
 * have to dig through the Docker volume to find a scan.
 *
 * Chromium-only and requires a secure context (https, or http://localhost —
 * which is how the OH PC serves its own UI). isSupported() gates all of it.
 */

export interface OcrCaptureForSave {
  value: string;
  confidence: number;
  raw_text: string;
  provider: string;
  scan_id: string;
}

const DB_NAME = "blade-rocking-local-save";
const DB_VERSION = 1;
const STORE_NAME = "handles";
const HANDLE_KEY = "ocrPhotoFolder";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE_NAME)) {
        req.result.createObjectStore(STORE_NAME);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error as Error);
  });
}

async function idbGet<T>(key: string): Promise<T | undefined> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).get(key);
    req.onsuccess = () => resolve(req.result as T | undefined);
    req.onerror = () => reject(req.error as Error);
  });
}

async function idbSet(key: string, value: unknown): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error as Error);
  });
}

async function idbDelete(key: string): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error as Error);
  });
}

export function isFolderPickerSupported(): boolean {
  return typeof window !== "undefined" && "showDirectoryPicker" in window;
}

export async function getStoredFolderHandle(): Promise<FileSystemDirectoryHandle | null> {
  if (!isFolderPickerSupported()) return null;
  const handle = await idbGet<FileSystemDirectoryHandle>(HANDLE_KEY);
  return handle ?? null;
}

/** Checks the existing grant without prompting the user. */
export async function hasReadWritePermission(handle: FileSystemDirectoryHandle): Promise<boolean> {
  return (await handle.queryPermission({ mode: "readwrite" })) === "granted";
}

/** Prompts the user if needed — must be called from a user-gesture handler (e.g. a click). */
export async function requestReadWritePermission(handle: FileSystemDirectoryHandle): Promise<boolean> {
  return (await handle.requestPermission({ mode: "readwrite" })) === "granted";
}

export async function chooseFolder(): Promise<FileSystemDirectoryHandle> {
  const handle = await window.showDirectoryPicker({ id: "blade-ocr-photos", mode: "readwrite" });
  await idbSet(HANDLE_KEY, handle);
  return handle;
}

export async function forgetFolder(): Promise<void> {
  await idbDelete(HANDLE_KEY);
}

function sanitizeSegment(s: string): string {
  return s.replace(/[\\/:*?"<>|]/g, "-").trim();
}

/** Writes `<name>.jpg` + `<name>.json` (the OCR detection) into the folder. */
export async function saveCaptureToFolder(
  handle: FileSystemDirectoryHandle,
  opts: {
    workOrderNumber: string;
    fieldLabel: string;
    photoBlob: Blob;
    ocr: OcrCaptureForSave;
  }
): Promise<void> {
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const baseName = sanitizeSegment(`${opts.workOrderNumber}_${opts.fieldLabel}_${ts}`);

  const photoHandle = await handle.getFileHandle(`${baseName}.jpg`, { create: true });
  const photoWritable = await photoHandle.createWritable();
  await photoWritable.write(opts.photoBlob);
  await photoWritable.close();

  const jsonHandle = await handle.getFileHandle(`${baseName}.json`, { create: true });
  const jsonWritable = await jsonHandle.createWritable();
  await jsonWritable.write(
    JSON.stringify(
      {
        work_order_number: opts.workOrderNumber,
        field: opts.fieldLabel,
        captured_at: new Date().toISOString(),
        ...opts.ocr,
      },
      null,
      2
    )
  );
  await jsonWritable.close();
}
