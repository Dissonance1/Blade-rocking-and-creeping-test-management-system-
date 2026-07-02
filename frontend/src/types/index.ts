/* ============================================================
   Blade Rocking & Creep Test Management System
   Shared TypeScript types — mirrors backend Pydantic schemas
   (roles are normalised to string arrays for easy UI consumption)
   ============================================================ */

// ─── Enumerations ─────────────────────────────────────────────────────────────

export type BladeStatus =
  | "CREATED"
  | "OH_INSPECTION"
  | "MEASUREMENTS_RECORDED"
  | "SENT_TO_ASSEMBLY"
  | "ASSEMBLY_RECEIVED"
  | "ASSEMBLY_VERIFIED"
  | "SLOT_ASSIGNED"
  | "BALANCING_IN_PROGRESS"
  | "BALANCING_COMPLETED"
  | "RETURNED_TO_OH"
  | "FINAL_VERIFICATION"
  | "COMPLETED"
  | "REJECTED"
  | "ON_HOLD"
  | "REOPENED";

export type UserRole =
  | "SUPER_ADMIN"
  | "OH_OPERATOR"
  | "ASSEMBLY_OPERATOR"
  | "QA_VIEWER";

// Matches backend MeasurementType enum exactly
export type MeasurementType = "INITIAL" | "INTERIM" | "FINAL";

// Backend NotificationType values + legacy aliases used in pages
export type NotificationType =
  // Backend values
  | "BLADE_RECEIVED"
  | "SLOT_PENDING"
  | "BALANCING_DONE"
  | "BLADE_REJECTED"
  | "VERIFICATION_PENDING"
  | "SYSTEM"
  | "WORKFLOW_UPDATED"
  | "GENERAL"
  // Legacy page aliases (map to above at runtime via fallback)
  | "BLADE_CREATED"
  | "STATUS_CHANGED"
  | "MEASUREMENT_ADDED"
  | "SLOT_ASSIGNED"
  | "BALANCING_COMPLETE"
  | "REJECTION"
  | "HOLD";

export type ReportType = "PDF" | "EXCEL";
// "READY" is what the backend sends; "COMPLETED" kept as alias for page compatibility
export type ReportStatus = "PENDING" | "GENERATING" | "READY" | "COMPLETED" | "FAILED";

// ─── User & Auth ──────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  username: string;
  full_name: string;
  /** Normalised to plain strings so `roles.includes("SUPER_ADMIN")` works */
  roles: UserRole[];
  station_id?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  last_login?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in?: number;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

// ─── Blade ────────────────────────────────────────────────────────────────────

export interface Blade {
  id: string;
  serial_number: string;
  melt_number: string;
  work_order_number: string;
  shop_order_number: string;
  part_number: string;
  nomenclature: string;
  engine_number?: string | null;
  batch_number?: string | null;
  engine_hours?: string | null;
  component_hours?: string | null;
  blade_type?: "LPTR" | "HPTR" | null;
  status: BladeStatus;
  current_station_id?: string | null;
  created_by_id: string;
  assigned_to_id?: string | null;
  ocr_serial_number?: string | null;
  ocr_mismatch_flag: boolean;
  ocr_mismatch_notes?: string | null;
  rejection_reason_id?: string | null;
  rejection_notes?: string | null;
  created_at: string;
  updated_at: string;
  // Optional eager-loaded relations (present when fetched via GET /blades/{id})
  measurements?: Measurement[];
  slot_allocation?: SlotAllocation | null;
  attachments?: Attachment[];
}

export interface BladeListItem {
  id: string;
  serial_number: string;
  melt_number: string;
  part_number: string;
  nomenclature: string;
  status: BladeStatus;
  work_order_number?: string | null;
  shop_order_number?: string | null;
  engine_number?: string | null;
  current_station_id?: string | null;
  assigned_to_id?: string | null;
  created_at: string;
  updated_at: string;
  /** Latest INITIAL measurement values (populated by list endpoint) */
  batch_number?: string | null;
  weight_grams?: number | null;
  static_moment_gcm?: number | null;
  height_data?: Record<string, number> | null;
}

export interface BladeCreateRequest {
  serial_number: string;
  melt_number: string;
  work_order_number: string;
  shop_order_number: string;
  part_number: string;
  nomenclature: string;
  engine_number?: string;
  batch_number?: string;
  engine_hours?: string;
  component_hours?: string;
  blade_type?: "LPTR" | "HPTR";
}

export interface BladeUpdateRequest {
  melt_number?: string;
  work_order_number?: string;
  shop_order_number?: string;
  engine_number?: string;
  assigned_to_id?: string;
}

export interface BladeActionRequest {
  remarks?: string;
}

export interface BladeRejectRequest {
  rejection_reason_id: string;
  notes: string;
}

// ─── Measurements ─────────────────────────────────────────────────────────────

export type HeightData = Record<string, number>;

export interface MeasurementApprover {
  id: string;
  username: string;
  full_name?: string | null;
}

export interface Measurement {
  id: string;
  blade_id: string;
  measurement_type: MeasurementType;
  batch_number?: string | null;
  weight_grams?: number | null;
  static_moment_gcm?: number | null;
  rocking_value?: number | null;
  creep_value?: number | null;
  height_data?: HeightData | null;
  measured_by: MeasurementApprover;
  station_id?: string | null;
  measured_at: string;
  is_approved: boolean;
  approved_by?: MeasurementApprover | null;
  approved_at?: string | null;
  notes?: string | null;
}

export interface MeasurementCreate {
  measurement_type: MeasurementType;
  weight_grams?: number;
  static_moment_gcm?: number;
  rocking_value?: number;
  creep_value?: number;
  height_data?: HeightData;
  station_id?: string;
  notes?: string;
}

// ─── Attachments ──────────────────────────────────────────────────────────────

export interface Attachment {
  id: string;
  blade_id: string;
  filename: string;
  original_filename: string;
  file_path: string;
  file_size_bytes: number;
  mime_type: string;
  attachment_type: "IMAGE" | "DOCUMENT" | "OCR_SCAN";
  uploaded_by_id: string;
  uploaded_at: string;
}

// ─── Slot Allocation ──────────────────────────────────────────────────────────

export interface SlotAllocation {
  id: string;
  blade_id: string;
  slot_number: string;

  group_id?: string | null;
  allocated_by_id: string;
  allocated_at: string;
  is_active: boolean;
  balancing_remarks?: string | null;
  is_balanced: boolean;
  unbalance_value?: number | null;
  previous_slot_number?: string | null;
}

export interface SlotAssignRequest {
  blade_id: string;
  slot_number: string;


  remarks?: string;
}

export interface SlotReassignRequest {
  blade_id: string;
  new_slot_number: string;
  reason: string;
}

export interface BalancingUpdate {
  is_balanced: boolean;
  balancing_remarks?: string;
  unbalance_value?: number;
}

// ─── Workflow ─────────────────────────────────────────────────────────────────

export interface WorkflowLog {
  id: string;
  blade_id: string;
  from_status: BladeStatus | null;
  to_status: BladeStatus;
  action_by_id: string;
  station_id?: string | null;
  remarks?: string | null;
  timestamp: string;
}

// Backend returns: { blade, logs, total_transitions }
export interface WorkflowHistoryResponse {
  blade: Blade;
  logs: WorkflowLog[];
  total_transitions: number;
}

// ─── Dashboard stats ──────────────────────────────────────────────────────────

export interface StationStat {
  station_id: string;
  station_name: string;
  station_code: string;
  blade_count: number;
}

export interface DashboardStats {
  /** Status → count map from backend */
  by_status: Partial<Record<BladeStatus, number>>;
  /** Array of per-station blade counts from backend */
  by_station: StationStat[];
  total_active: number;
  total_completed: number;
  total_rejected: number;
  /** Unbalanced slot alerts (from balancing status) */
  unbalanced_slots?: { slot_number: string; blade_id: string }[];
  total_unbalanced?: number;
}

// ─── Notifications ────────────────────────────────────────────────────────────

export interface Notification {
  id: string;
  user_id?: string | null;
  title: string;
  body: string;
  notification_type: NotificationType;
  is_read: boolean;
  read_at?: string | null;
  blade_id?: string | null;
  created_at: string;
  expires_at?: string | null;
}

export interface NotificationQueryParams {
  page?: number;
  page_size?: number;
  unread_only?: boolean;
}

// ─── Station ──────────────────────────────────────────────────────────────────

export interface Station {
  id: string;
  name: string;
  code: string;
  station_type: "OH" | "ASSEMBLY" | "QA" | "ADMIN";
  is_active: boolean;
  location?: string | null;
}

// ─── Rejection Reason ─────────────────────────────────────────────────────────

export interface RejectionReason {
  id: string;
  code: string;
  description: string;
  is_active: boolean;
}

// ─── Reports ──────────────────────────────────────────────────────────────────

export interface ReportFilters {
  date_from?: string;
  date_to?: string;
  statuses?: BladeStatus[];
  station_id?: string | null;
  include_rejected?: boolean;
}

export interface Report {
  id: string;
  name: string;
  report_type: ReportType;
  status: ReportStatus;
  generated_by_id: string;
  created_at: string;
  completed_at?: string | null;
  file_path?: string | null;
  /** Alias for file_path for backward compat */
  file_url?: string | null;
  file_size_bytes?: number | null;
  filter_params?: ReportFilters | null;
  error_message?: string | null;
}


// ─── Pagination ───────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ─── Blade search params ──────────────────────────────────────────────────────

export interface BladeSearchParams {
  skip?: number;
  limit?: number;
  /** Alias for limit used by some pages */
  page_size?: number;
  page?: number;
  status?: BladeStatus;
  statuses?: BladeStatus[];
  batch_number?: string;
  station_id?: string;
  q?: string;
  date_from?: string;
  date_to?: string;
}

// ─── API error shapes ─────────────────────────────────────────────────────────

export interface ApiValidationError {
  msg: string;
  loc: string[];
  type: string;
}

export interface ApiError {
  detail: string | ApiValidationError[];
}

// ─── WebSocket payloads ───────────────────────────────────────────────────────

export interface WsNotificationPayload {
  type: "notification";
  data: Notification;
}

export interface WsPingPayload {
  type: "ping";
}

export type WsPayload = WsNotificationPayload | WsPingPayload;
