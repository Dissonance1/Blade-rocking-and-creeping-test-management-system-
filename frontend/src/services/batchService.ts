import api from "./api";

export interface BatchEvent {
  id: string;
  batch_number: string;
  event_type:
    | "SENT_TO_ASSEMBLY"
    | "RECEIVED_BY_ASSEMBLY"
    | "ACCEPTED"
    | "REJECTED"
    | "MODIFIED"
    | "SLOTS_ALLOCATED";
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
  | "MODIFIED"
  | "SLOTS_ALLOCATED";

export interface BatchSummary {
  batch_number: string;
  blade_count: number;
  blades_sent: number;
  blades_completed: number;
  hptr_count: number;
  hptr_slotted_count: number;
  hptr_balanced_count: number;
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
  /** HPTR blades in the batch — always skipped, since HPTR never leaves OH. */
  hptr_skipped_count: number;
  message: string;
}

export interface HptrSlotAssignment {
  blade_id: string;
  slot_number: number;
}

export interface HptrAssignSlotResult {
  batch_number: string;
  blade_type: "HPTR";
  blades_assigned: number;
  start_slot: number;
  w1_total: number;
  w2_total: number;
  weight_diff: number;
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
      { blade_type: "LPTR", imbalance_slot: imbalanceSlot, total_slots: totalSlots }
    );
    return data;
  },

  /**
   * Persists the operator-confirmed HPTR blade-to-slot mapping. Unlike LPTR,
   * HPTR allocation isn't computed server-side — the Slot Allocation/Set
   * Making tabs compute the mapping (and any manual W1/W2 swaps) client-side
   * via `hptrBalancing.ts`, and this call just saves the final result.
   */
  assignHptrSlots: async (
    batchNumber: string,
    startSlot: number,
    totalSlots: number,
    assignments: HptrSlotAssignment[],
    unbalanceValue?: number
  ): Promise<HptrAssignSlotResult> => {
    const { data } = await api.post(
      `/batches/${batchNumber}/assign-slot`,
      {
        blade_type: "HPTR",
        start_slot: startSlot,
        total_slots: totalSlots,
        unbalance_value: unbalanceValue,
        assignments,
      }
    );
    return data;
  },

  getRockingCreep: async (batchNumber: string): Promise<BladeRockingCreepEntry[]> => {
    const { data } = await api.get<BladeRockingCreepEntry[]>(
      `/batches/${batchNumber}/rocking-creep`
    );
    return data;
  },

  /**
   * Physical balancing testing found the set still unbalanced — deactivates
   * the batch's saved HPTR slot allocation and resets the blades to
   * Measurements Recorded so OH can redo Slot Allocation from scratch.
   */
  rejectHptrSlots: async (
    batchNumber: string,
    reason?: string
  ): Promise<{ batch_number: string; blades_reset: number; message: string }> => {
    const { data } = await api.post(`/batches/${batchNumber}/reject-hptr-slots`, { reason });
    return data;
  },

  /**
   * Physical balancing testing confirmed the set is balanced — transitions
   * every HPTR blade in the batch to BALANCING_COMPLETED. Once complete,
   * the batch stops showing up as selectable in the OH Slot Allocation page.
   */
  completeHptrBalancing: async (
    batchNumber: string,
    remarks?: string
  ): Promise<{ batch_number: string; blades_completed: number; message: string }> => {
    const { data } = await api.post(`/batches/${batchNumber}/complete-hptr-balancing`, { remarks });
    return data;
  },
};
