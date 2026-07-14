/* ============================================================
   Assembly station TypeScript types
   Mirrors backend app/schemas/assembly.py
   ============================================================ */

export type AssemblyVerificationStatus =
  | "PENDING"
  | "ACCEPTED"
  | "MODIFIED"
  | "REJECTED";

// ---------------------------------------------------------------------------
// Batch receipt
// ---------------------------------------------------------------------------

export interface BatchReceiveRequest {
  station_id?: string | null;
  notes?: string | null;
}

export interface BatchReceiptResponse {
  id: string;
  work_order_number: string;
  received_at: string;
  received_by_id: string;
  station_id: string | null;
  total_expected: number;
  notes: string | null;
  created_at: string;
}

export interface BatchProgressResponse {
  work_order_number: string;
  total_expected: number;
  assembly_received: number;
  assembly_verified: number;
  assembly_rejected: number;
  pending: number;
  set_making_ready: boolean;
  /** HPTR never leaves OH — readiness means every HPTR blade in the batch has recorded measurements. */
  hptr_total: number;
  hptr_measurements_recorded: number;
  hptr_set_making_ready: boolean;
}

// ---------------------------------------------------------------------------
// Per-blade verification
// ---------------------------------------------------------------------------

export interface BladeVerifyRequest {
  qr_scan_result?: string | null;
  ocr_blade_number?: string | null;
  assembly_weight?: number | null;
  assembly_dti_h1?: number | null;
  assembly_dti_h2?: number | null;
  assembly_dti_h3?: number | null;
  assembly_dti_h4?: number | null;
}

export interface BladeAcceptRequest {
  notes?: string | null;
  assembly_weight?: number | null;
  assembly_dti_h1?: number | null;
  assembly_dti_h2?: number | null;
  assembly_dti_h3?: number | null;
  assembly_dti_h4?: number | null;
}

export interface BladeRejectRequest {
  notes: string;
}

export interface AssemblyBladeRecord {
  id: string;
  blade_id: string;
  batch_receipt_id: string;
  qr_scan_result: string | null;
  ocr_blade_number: string | null;
  assembly_weight: number | null;
  assembly_dti_h1: number | null;
  assembly_dti_h2: number | null;
  assembly_dti_h3: number | null;
  assembly_dti_h4: number | null;
  oh_weight: number | null;
  oh_dti_h1: number | null;
  oh_dti_h2: number | null;
  oh_dti_h3: number | null;
  oh_dti_h4: number | null;
  weight_delta: number | null;
  status: AssemblyVerificationStatus;
  verification_notes: string | null;
  verified_by_id: string | null;
  verified_at: string | null;
  created_at: string;
}

export interface FieldValidation {
  field: string;
  oh_value: number | null;
  assembly_value: number | null;
  delta: number | null;
  within_tolerance: boolean;
  tolerance_used: number | null;
}

export interface BladeVerifyResponse {
  record: AssemblyBladeRecord;
  serial_number_match: boolean;
  ocr_match: boolean;
  validations: FieldValidation[];
  all_within_tolerance: boolean;
  suggested_action: "ACCEPT" | "REVIEW" | "REJECT";
}

// ---------------------------------------------------------------------------
// Set-making
// ---------------------------------------------------------------------------

export interface SetMakingResponse {
  work_order_number: string;
  status: string;
  total_blades: number;
  message: string;
}
