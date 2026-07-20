import api from "./api";
import type { LptrBalancingCheck, LptrCorrectionType, LptrEmptyRotorReading, LptrManualCorrection } from "@/types";

export const lptrService = {
  getEmptyRotorReading: async (workOrderNumber: string): Promise<LptrEmptyRotorReading | null> => {
    try {
      const { data } = await api.get<LptrEmptyRotorReading>(
        `/lptr/${workOrderNumber}/empty-rotor`
      );
      return data;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) return null;
      throw err;
    }
  },

  saveEmptyRotorReading: async (
    workOrderNumber: string,
    unbalanceSlot: number,
    unbalanceValue: number
  ): Promise<LptrEmptyRotorReading> => {
    const { data } = await api.post<LptrEmptyRotorReading>(
      `/lptr/${workOrderNumber}/empty-rotor`,
      { unbalance_slot: unbalanceSlot, unbalance_value: unbalanceValue }
    );
    return data;
  },

  createBalancingCheck: async (
    workOrderNumber: string,
    stage: number,
    measuredUnbalance: number,
    remarks?: string
  ): Promise<LptrBalancingCheck> => {
    const { data } = await api.post<LptrBalancingCheck>(
      `/lptr/${workOrderNumber}/balancing-check`,
      { stage, measured_unbalance: measuredUnbalance, remarks }
    );
    return data;
  },

  listBalancingChecks: async (workOrderNumber: string): Promise<LptrBalancingCheck[]> => {
    const { data } = await api.get<LptrBalancingCheck[]>(
      `/lptr/${workOrderNumber}/balancing-checks`
    );
    return data;
  },

  createManualCorrection: async (
    workOrderNumber: string,
    stage: number,
    correctionType: LptrCorrectionType,
    description: string,
    bladeId?: string,
    slotNumber?: string
  ): Promise<LptrManualCorrection> => {
    const { data } = await api.post<LptrManualCorrection>(
      `/lptr/${workOrderNumber}/manual-correction`,
      {
        stage,
        correction_type: correctionType,
        description,
        blade_id: bladeId,
        slot_number: slotNumber,
      }
    );
    return data;
  },

  listManualCorrections: async (workOrderNumber: string): Promise<LptrManualCorrection[]> => {
    const { data } = await api.get<LptrManualCorrection[]>(
      `/lptr/${workOrderNumber}/manual-corrections`
    );
    return data;
  },
};
