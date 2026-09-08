import { useCallback, useEffect, useState } from "react";
import {
  chooseSaveFolder,
  forgetSaveFolder,
  getSaveFolder,
  saveCaptureToFolder,
  type OcrCaptureForSave,
} from "@/services/localSaveFolder";

export type LocalSaveFolderStatus = "unavailable" | "checking" | "not-set" | "ready";

/**
 * Backs the "save OCR photos to a local folder" affordance in Blade Entry.
 * The folder is chosen once (native OS dialog on the OAK-1 companion
 * service's PC) and stays chosen — no browser permission grant to lapse or
 * reconnect, unlike the File System Access API this used to go through.
 */
export function useLocalSaveFolder() {
  const [status, setStatus] = useState<LocalSaveFolderStatus>("checking");
  const [folderName, setFolderName] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStatus((prev) => (prev === "ready" ? prev : "checking"));
    try {
      const { path, name } = await getSaveFolder();
      setFolderName(name);
      setStatus(path ? "ready" : "not-set");
    } catch {
      setFolderName(null);
      setStatus("unavailable");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const choose = useCallback(async () => {
    try {
      const { name } = await chooseSaveFolder();
      setFolderName(name);
      setStatus("ready");
    } catch {
      // Operator cancelled the dialog, or the companion service is
      // unreachable — leave state as-is either way.
    }
  }, []);

  const forget = useCallback(async () => {
    await forgetSaveFolder();
    setFolderName(null);
    setStatus("not-set");
  }, []);

  /** Returns false when the capture was skipped (no folder configured, or the
   * companion service is unreachable) rather than actually written — callers
   * should surface that to the operator instead of assuming a silent no-op
   * means "saved". */
  const saveCapture = useCallback(
    async (opts: { workOrderNumber: string; fieldLabel: string; photoBlob: Blob; ocr: OcrCaptureForSave }) => {
      if (status !== "ready") return false;
      return saveCaptureToFolder(opts);
    },
    [status]
  );

  return { supported: status !== "unavailable", status, folderName, choose, forget, saveCapture };
}
