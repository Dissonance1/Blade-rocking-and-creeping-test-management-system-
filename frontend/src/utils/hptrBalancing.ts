import type { BladeListItem } from "@/types";

/**
 * HPTR slot allocation & set-making logic.
 *
 * HPTR blades never leave OH, and use a different balancing procedure than
 * LPTR (see `SlotAllocationPage.tsx` / `utils/balancing.ts` for LPTR's
 * heavy/light interleave):
 *
 * 1. Sort the batch's HPTR blades by weight descending.
 * 2. Pair the heaviest with the Assembly-provided `startSlot`, and the
 *    lightest with its opposite slot (45 slots away on the 90-slot rotor),
 *    then alternate inward (2nd heaviest -> startSlot+1, 2nd lightest ->
 *    opposite(startSlot+1), ...).
 * 3. Split the rotor into W1 (slots 1..45) and W2 (slots 46..90) and sum
 *    each half's weight.
 * 4. The half containing `startSlot` must be heavier than the other half by
 *    1.5-2.0 g. If not, the operator manually swaps which blade occupies
 *    which slot (slot numbers themselves never change) until it is.
 */

export const HPTR_TOTAL_SLOTS = 90;
export const HPTR_TARGET_DIFF_MIN = 1.5;
export const HPTR_TARGET_DIFF_MAX = 2.0;

export interface HptrAllocationEntry {
  blade: BladeListItem;
  slot: number;
}

/** Opposite slot on the rotor: exactly half the total slots away, wrapping around. */
export function oppositeSlot(slot: number, totalSlots: number = HPTR_TOTAL_SLOTS): number {
  const half = totalSlots / 2;
  return ((slot - 1 + half) % totalSlots) + 1;
}

/**
 * Steps 1-2: sort by weight descending, then pair heaviest/lightest
 * alternating inward from `startSlot` and its opposite.
 */
export function computeInitialHptrSlots(
  blades: BladeListItem[],
  startSlot: number,
  totalSlots: number = HPTR_TOTAL_SLOTS
): HptrAllocationEntry[] {
  const sorted = [...blades].sort((a, b) => (b.weight_grams ?? 0) - (a.weight_grams ?? 0));
  const n = sorted.length;
  const pairCount = Math.floor(n / 2);
  const entries: HptrAllocationEntry[] = [];

  for (let i = 0; i < pairCount; i++) {
    const heavyBlade = sorted[i];
    const lightBlade = sorted[n - 1 - i];
    if (!heavyBlade || !lightBlade) continue;
    const heavySlot = ((startSlot - 1 + i) % totalSlots) + 1;
    const lightSlot = oppositeSlot(heavySlot, totalSlots);
    entries.push({ blade: heavyBlade, slot: heavySlot });
    entries.push({ blade: lightBlade, slot: lightSlot });
  }
  // Odd blade count (partial batch): middle blade takes the next slot in
  // sequence — it has no opposite pairing partner.
  if (n % 2 === 1) {
    const midBlade = sorted[pairCount];
    if (midBlade) {
      const midSlot = ((startSlot - 1 + pairCount) % totalSlots) + 1;
      entries.push({ blade: midBlade, slot: midSlot });
    }
  }
  return entries;
}

export interface HptrHalves {
  /** Slots 1..half = W1, half+1..totalSlots = W2 */
  half: number;
  w1Total: number;
  w2Total: number;
  diff: number;
  startSlotHalf: "W1" | "W2";
}

/** Step 3-4: split into W1/W2 and compute the weight difference. */
export function computeHalves(
  entries: HptrAllocationEntry[],
  startSlot: number,
  totalSlots: number = HPTR_TOTAL_SLOTS
): HptrHalves {
  const half = totalSlots / 2;
  let w1Total = 0;
  let w2Total = 0;
  for (const { blade, slot } of entries) {
    const weight = blade.weight_grams ?? 0;
    if (slot <= half) w1Total += weight;
    else w2Total += weight;
  }
  return {
    half,
    w1Total,
    w2Total,
    diff: Math.abs(w1Total - w2Total),
    startSlotHalf: startSlot <= half ? "W1" : "W2",
  };
}

/**
 * True when the half containing `startSlot` is heavier than the other half
 * by 1.5-2.0 g, per the set-making requirement.
 */
export function isSetMakingValid(halves: HptrHalves): boolean {
  const startHalfIsHeavier =
    halves.startSlotHalf === "W1" ? halves.w1Total > halves.w2Total : halves.w2Total > halves.w1Total;
  return (
    startHalfIsHeavier &&
    halves.diff >= HPTR_TARGET_DIFF_MIN &&
    halves.diff <= HPTR_TARGET_DIFF_MAX
  );
}

/**
 * Manual balancing swap: exchange which blade occupies each of two slots.
 * Slot numbers themselves never change, only the blade assigned to them.
 */
export function swapBladesBetweenSlots(
  entries: HptrAllocationEntry[],
  slotA: number,
  slotB: number
): HptrAllocationEntry[] {
  return entries.map((entry) => {
    if (entry.slot === slotA) return { ...entry, slot: slotB };
    if (entry.slot === slotB) return { ...entry, slot: slotA };
    return entry;
  });
}

/** Split entries into W1/W2 groups, each sorted by slot number ascending. */
export function groupByHalf(
  entries: HptrAllocationEntry[],
  totalSlots: number = HPTR_TOTAL_SLOTS
): { w1: HptrAllocationEntry[]; w2: HptrAllocationEntry[] } {
  const half = totalSlots / 2;
  const w1 = entries.filter((e) => e.slot <= half).sort((a, b) => a.slot - b.slot);
  const w2 = entries.filter((e) => e.slot > half).sort((a, b) => a.slot - b.slot);
  return { w1, w2 };
}

export interface SwapSuggestion {
  slotA: number;
  slotB: number;
  bladeASerial: string;
  bladeBSerial: string;
  /** |W1 - W2| after applying this swap. */
  resultingDiff: number;
  /** True if this swap alone lands the set within the 1.5-2.0 g target. */
  meetsTarget: boolean;
}

/**
 * Suggest a single blade-to-blade swap (one slot from each half) that brings
 * the set closest to the 1.5-2.0 g target — an assistive hint only. The
 * operator still applies it (or ignores it) manually via the swap controls;
 * this does not replace the manual, live-recalculating workflow.
 *
 * Only cross-half swaps change the W1/W2 balance (swapping two slots within
 * the same half leaves both totals unchanged), so the search is limited to
 * W1 x W2 pairs.
 */
export function suggestBalancingSwap(
  entries: HptrAllocationEntry[],
  startSlot: number,
  totalSlots: number = HPTR_TOTAL_SLOTS
): SwapSuggestion | null {
  const halves = computeHalves(entries, startSlot, totalSlots);
  const { w1, w2 } = groupByHalf(entries, totalSlots);
  if (w1.length === 0 || w2.length === 0) return null;

  const sign = halves.startSlotHalf === "W1" ? 1 : -1;
  const currentSignedDiff = halves.w1Total - halves.w2Total;
  const targetCenter = sign * ((HPTR_TARGET_DIFF_MIN + HPTR_TARGET_DIFF_MAX) / 2);

  let best: SwapSuggestion | null = null;
  let bestScore = Infinity;

  for (const a of w1) {
    const wA = a.blade.weight_grams ?? 0;
    for (const b of w2) {
      const wB = b.blade.weight_grams ?? 0;
      // Swapping slotA <-> slotB moves blade A into W2 and blade B into W1.
      const newSignedDiff = currentSignedDiff + 2 * (wB - wA);
      const meets =
        sign === 1
          ? newSignedDiff >= HPTR_TARGET_DIFF_MIN && newSignedDiff <= HPTR_TARGET_DIFF_MAX
          : newSignedDiff <= -HPTR_TARGET_DIFF_MIN && newSignedDiff >= -HPTR_TARGET_DIFF_MAX;
      const score = Math.abs(newSignedDiff - targetCenter);
      if (score < bestScore) {
        bestScore = score;
        best = {
          slotA: a.slot,
          slotB: b.slot,
          bladeASerial: a.blade.serial_number,
          bladeBSerial: b.blade.serial_number,
          resultingDiff: Math.abs(newSignedDiff),
          meetsTarget: meets,
        };
      }
    }
  }

  return best;
}
