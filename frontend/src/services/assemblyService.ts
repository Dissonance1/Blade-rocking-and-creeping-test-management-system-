import api from "./api";
import type {
  BatchReceiveRequest,
  BatchReceiptResponse,
  BatchProgressResponse,
  BladeVerifyRequest,
  BladeVerifyResponse,
  AssemblyBladeRecord,
  BladeAcceptRequest,
  BladeRejectRequest,
  SetMakingResponse,
} from "@/types/assembly";

export const assemblyService = {
  /** Mark a batch as received at Assembly — creates AssemblyBatchReceipt and transitions blades */
  receiveBatch: (batchNumber: string, data: BatchReceiveRequest = {}) =>
    api
      .post<BatchReceiptResponse>(`/assembly/batches/${batchNumber}/receive`, data)
      .then((r) => r.data),

  /** Fetch the receipt for a batch (404 if not yet received at assembly) */
  getBatchReceipt: (batchNumber: string) =>
    api
      .get<BatchReceiptResponse>(`/assembly/batches/${batchNumber}/receipt`)
      .then((r) => r.data),

  /** Verification progress: received / verified / rejected / pending counts */
  getBatchProgress: (batchNumber: string) =>
    api
      .get<BatchProgressResponse>(`/assembly/batches/${batchNumber}/progress`)
      .then((r) => r.data),

  /** Blades in this batch that have assembly records (verified / rejected) */
  getBatchBlades: (batchNumber: string) =>
    api
      .get<AssemblyBladeRecord[]>(`/assembly/batches/${batchNumber}/blades`)
      .then((r) => r.data),

  /**
   * Submit scan + measurements for a blade.
   * Returns validation result including per-field comparison with OH values
   * and a suggested action (ACCEPT | REVIEW | REJECT).
   */
  verifyBlade: (bladeId: string, data: BladeVerifyRequest) =>
    api
      .post<BladeVerifyResponse>(`/assembly/blades/${bladeId}/verify`, data)
      .then((r) => r.data),

  /** Accept a blade (optionally override readings with corrected values) */
  acceptBlade: (bladeId: string, data: BladeAcceptRequest = {}) =>
    api
      .post<AssemblyBladeRecord>(`/assembly/blades/${bladeId}/accept`, data)
      .then((r) => r.data),

  /** Reject a blade with a mandatory reason */
  rejectBlade: (bladeId: string, data: BladeRejectRequest) =>
    api
      .post<AssemblyBladeRecord>(`/assembly/blades/${bladeId}/reject`, data)
      .then((r) => r.data),

  /** Trigger set-making — only succeeds when all blades are ASSEMBLY_VERIFIED */
  startSetMaking: (batchNumber: string, notes?: string) =>
    api
      .post<SetMakingResponse>(`/assembly/batches/${batchNumber}/start-setmaking`, { notes })
      .then((r) => r.data),
};
