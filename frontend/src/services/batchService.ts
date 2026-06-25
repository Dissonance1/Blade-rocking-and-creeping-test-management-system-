import api from "./api";

export interface BatchEvent {
  id: string;
  batch_number: string;
  event_type:
    | "SENT_TO_ASSEMBLY"
    | "RECEIVED_BY_ASSEMBLY"
    | "ACCEPTED"
    | "REJECTED"
    | "MODIFIED";
  action_by: { id: string; username: string; full_name: string } | null;
  remarks: string | null;
  changes: Record<string, unknown> | null;
  timestamp: string;
}

export type BatchStatus =
  | "CREATED"
  | "SENT_TO_ASSEMBLY"
  | "RECEIVED_BY_ASSEMBLY"
  | "ACCEPTED"
  | "REJECTED"
  | "MODIFIED";

export interface BatchSummary {
  batch_number: string;
  blade_count: number;
  blades_sent: number;
  current_status: BatchStatus;
  current_status_label: string;
  first_blade_at: string | null;
  first_sent_at: string | null;
  last_event: BatchEvent | null;
  work_order_number: string | null;
  part_number: string | null;
  engine_number: string | null;
  nomenclature: string | null;
}

export interface BatchDetail extends BatchSummary {
  events: BatchEvent[];
}

export interface BatchSendResult {
  batch_number: string;
  total_blades: number;
  sent_count: number;
  skipped_count: number;
  message: string;
}

export interface BladeRockingCreepEntry {
  blade_id: string;
  serial_number: string;
  melt_number: string;
  blade_type: "LPTR" | "HPTR";
  status: string;
  slot_number: string | null;
  measurement_id: string | null;
  rocking_value: number | null;
  creep_value: number | null;
}

export const batchService = {
  list: async (params?: { has_slot_allocations?: boolean }): Promise<BatchSummary[]> => {
    const { data } = await api.get<BatchSummary[]>("/batches/", { params });
    return data;
  },

  get: async (batchNumber: string): Promise<BatchDetail> => {
    const { data } = await api.get<BatchDetail>(`/batches/${batchNumber}`);
    return data;
  },

  sendToAssembly: async (
    batchNumber: string,
    remarks?: string
  ): Promise<BatchSendResult> => {
    const { data } = await api.post<BatchSendResult>(
      `/batches/${batchNumber}/send-to-assembly`,
      { remarks }
    );
    return data;
  },

  receive: async (batchNumber: string, remarks?: string): Promise<BatchEvent> => {
    const { data } = await api.post<BatchEvent>(
      `/batches/${batchNumber}/receive`,
      { remarks }
    );
    return data;
  },

  accept: async (batchNumber: string, remarks?: string): Promise<BatchEvent> => {
    const { data } = await api.post<BatchEvent>(
      `/batches/${batchNumber}/accept`,
      { remarks }
    );
    return data;
  },

  reject: async (batchNumber: string, remarks?: string): Promise<BatchEvent> => {
    const { data } = await api.post<BatchEvent>(
      `/batches/${batchNumber}/reject`,
      { remarks }
    );
    return data;
  },

  modify: async (
    batchNumber: string,
    modifications: Array<{
      blade_id: string;
      serial_number: string;
      original: Record<string, unknown>;
      updated: Record<string, unknown>;
    }>,
    remarks: string
  ): Promise<BatchEvent> => {
    const { data } = await api.post<BatchEvent>(
      `/batches/${batchNumber}/modify`,
      { remarks, modifications }
    );
    return data;
  },

  assignSlot: async (
    batchNumber: string,
    imbalanceSlot: number,
    totalSlots: number
  ): Promise<{ batch_number: string; blades_assigned: number; message: string }> => {
    const { data } = await api.post(
      `/batches/${batchNumber}/assign-slot`,
      { imbalance_slot: imbalanceSlot, total_slots: totalSlots }
    );
    return data;
  },

  getRockingCreep: async (batchNumber: string): Promise<BladeRockingCreepEntry[]> => {
    const { data } = await api.get<BladeRockingCreepEntry[]>(
      `/batches/${batchNumber}/rocking-creep`
    );
    return data;
  },
};
