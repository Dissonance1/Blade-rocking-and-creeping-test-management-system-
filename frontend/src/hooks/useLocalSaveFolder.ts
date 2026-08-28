import { useCallback, useEffect, useRef, useState } from "react";
import {
  chooseFolder,
  forgetFolder,
  getStoredFolderHandle,
  hasReadWritePermission,
  isFolderPickerSupported,
  requestReadWritePermission,
  saveCaptureToFolder,
  type OcrCaptureForSave,
} from "@/services/localSaveFolder";

export type LocalSaveFolderStatus =
  | "unsupported"
  | "checking"
  | "not-set"
  | "ready"
  | "permission-needed";

/**
 * Backs the "save OCR photos to a local folder" affordance in Blade Entry.
 * The folder handle is remembered across sessions (IndexedDB), but the
 * browser drops its permission grant on reload — `permission-needed` means
 * the folder is remembered, it just needs a click to re-grant.
 */
export function useLocalSaveFolder() {
  const supported = isFolderPickerSupported();
  const [status, setStatus] = useState<LocalSaveFolderStatus>(supported ? "checking" : "unsupported");
  const [folderName, setFolderName] = useState<string | null>(null);
  const handleRef = useRef<FileSystemDirectoryHandle | null>(null);

  useEffect(() => {
    if (!supported) return;
    let cancelled = false;
    void (async () => {
      const handle = await getStoredFolderHandle();
      if (cancelled) return;
      if (!handle) {
        setStatus("not-set");
        return;
      }
      handleRef.current = handle;
      setFolderName(handle.name);
      setStatus((await hasReadWritePermission(handle)) ? "ready" : "permission-needed");
    })();
    return () => {
      cancelled = true;
    };
  }, [supported]);

  const choose = useCallback(async () => {
    try {
      const handle = await chooseFolder();
      handleRef.current = handle;
      setFolderName(handle.name);
      setStatus("ready");
    } catch {
      // User cancelled the picker — leave state as-is.
    }
  }, []);

  /** Re-requests permission for the remembered folder. Must run from a click handler. */
  const reconnect = useCallback(async () => {
    const handle = handleRef.current;
    if (!handle) return;
    setStatus((await requestReadWritePermission(handle)) ? "ready" : "permission-needed");
  }, []);

  const forget = useCallback(async () => {
    await forgetFolder();
    handleRef.current = null;
    setFolderName(null);
    setStatus("not-set");
  }, []);

  /** Returns false when the capture was skipped (folder not connected/ready)
   * rather than actually written — callers should surface that to the
   * operator instead of assuming a silent no-op means "saved". */
  const saveCapture = useCallback(
    async (opts: { workOrderNumber: string; fieldLabel: string; photoBlob: Blob; ocr: OcrCaptureForSave }) => {
      const handle = handleRef.current;
      if (!handle || status !== "ready") return false;
      await saveCaptureToFolder(handle, opts);
      return true;
    },
    [status]
  );

  return { supported, status, folderName, choose, reconnect, forget, saveCapture };
}
