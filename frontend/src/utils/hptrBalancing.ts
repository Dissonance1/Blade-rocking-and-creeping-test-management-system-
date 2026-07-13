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
 * The rotor's own pre-existing unbalance (the Assembly-provided
 * `unbalanceValue`, `y`) and the W1/W2 weight difference computed here
 * (`halves.diff`, `x`) partially cancel out. What actually has to land in
 * the 1.5-2.0 g spec band is the net of the two — `|x - y|` — not `x` alone.
 */
export function computeAdjustedDiff(halves: HptrHalves, unbalanceValue: number): number {
  return Math.abs(halves.diff - unbalanceValue);
}

/**
 * True when the half containing `startSlot` is heavier than the other half,
 * and the net of that difference (`x`) against the rotor's own pre-existing
 * unbalance (`y`) — `|x - y|` — falls within the 1.5-2.0 g target band.
 */
export function isSetMakingValid(halves: HptrHalves, unbalanceValue: number = 0): boolean {
  const startHalfIsHeavier =
    halves.startSlotHalf === "W1" ? halves.w1Total > halves.w2Total : halves.w2Total > halves.w1Total;
  const adjustedDiff = computeAdjustedDiff(halves, unbalanceValue);
  return (
    startHalfIsHeavier &&
    adjustedDiff >= HPTR_TARGET_DIFF_MIN &&
    adjustedDiff <= HPTR_TARGET_DIFF_MAX
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

/**
 * Number of pair-indices (beyond the anchor, i=0) that are protected from
 * swapping unless the fallback tier is needed — pair-indices 1..NEAR_PAIR_COUNT.
 * 6 pairs = the 6 next-heaviest blades (top) + their 6 paired next-lightest
 * blades (bottom) = 12 blades total.
 */
const NEAR_PAIR_COUNT = 6;

/**
 * Largest flip-combination size the suggestion search will try. Scattered
 * (non-adjacent) picks are allowed, but an operator won't want to hand-apply
 * more than a handful of flips anyway, and combination counts explode
 * combinatorially past this — the search already stops at the smallest size
 * that works, so this cap only matters when no small solution exists.
 */
const MAX_COMBO_SIZE = 8;

/** All k-sized subsets of `arr` (order preserved, no repeats), ascending by first-picked index. */
function* combinations(arr: number[], k: number): Generator<number[]> {
  if (k === 0) {
    yield [];
    return;
  }
  for (let i = 0; i <= arr.length - k; i++) {
    for (const rest of combinations(arr.slice(i + 1), k - 1)) {
      yield [arr[i]!, ...rest];
    }
  }
}

/** One heavy/light pair "flipped" — the two blades exchange which of the pair's two (already-opposite) slots they occupy. */
export interface PairFlip {
  pairIndex: number;
  slotA: number;
  slotB: number;
  bladeASerial: string;
  bladeBSerial: string;
}

export interface SwapSuggestion {
  /** One or more pair-flips to apply together (fewest possible that reach the target). */
  flips: PairFlip[];
  /** |x - y| after applying every flip (x = |W1 - W2|, y = unbalanceValue). */
  resultingDiff: number;
  /** True if this combination of flips lands the set within the 1.5-2.0 g target. */
  meetsTarget: boolean;
  /** True if reaching the target required dipping into the protected near-anchor pairs. */
  usedNearPairs: boolean;
}

/**
 * Suggest the fewest possible pair-flips that bring the set closest to the
 * 1.5-2.0 g target — an assistive hint only. The operator still applies it
 * (or ignores it) via "Apply Suggestion"; this does not replace the manual,
 * live-recalculating workflow.
 *
 * Every blade was originally placed as part of a heavy/light pair: the
 * pair's heavy blade at slot `startSlot + i` and its light counterpart at
 * that slot's exact opposite (see `computeInitialHptrSlots`). A "flip"
 * exchanges which of the pair's two (already-opposite) slots each blade
 * occupies — it never proposes swapping blades that weren't already paired
 * together, and it never touches:
 *   - pair 0 (the anchor: heaviest blade at `startSlot`, lightest at its
 *     opposite) — this pair is never touched, under any circumstance.
 *   - pairs 1..NEAR_PAIR_COUNT (the next-most-extreme pairs) — only used as
 *     a fallback if no combination of the remaining pairs reaches the target.
 *
 * Search order: try every single eligible pair first (fewest changes wins);
 * if no single flip reaches the target, try every 2-pair combination, then
 * 3, and so on — the pairs in a combination don't need to be adjacent
 * (scattered picks are fine) as long as the flip count stays minimal and
 * pairs 0..NEAR_PAIR_COUNT stay untouched (until the fallback tier).
 *
 * `unbalanceValue` (`y`) is the rotor's own pre-existing unbalance — the
 * target band applies to `|x - y|` (`x` = |W1 - W2|), not `x` alone.
 */
export function suggestBalancingSwap(
  entries: HptrAllocationEntry[],
  startSlot: number,
  unbalanceValue: number = 0,
  totalSlots: number = HPTR_TOTAL_SLOTS
): SwapSuggestion | null {
  const half = totalSlots / 2;
  const halves = computeHalves(entries, startSlot, totalSlots);
  const sign = halves.startSlotHalf === "W1" ? 1 : -1;
  const currentSignedDiff = halves.w1Total - halves.w2Total;
  const targetMid = (HPTR_TARGET_DIFF_MIN + HPTR_TARGET_DIFF_MAX) / 2;

  const bySlot = new Map(entries.map((e) => [e.slot, e]));

  // Every pair index i (0 = anchor) maps to a fixed physical slot pairing,
  // regardless of which blade currently sits at either slot.
  const pairSlots = new Map<number, { heavySlot: number; lightSlot: number }>();
  for (let i = 0; i < half; i++) {
    const heavySlot = ((startSlot - 1 + i) % totalSlots) + 1;
    const lightSlot = oppositeSlot(heavySlot, totalSlots);
    if (bySlot.has(heavySlot) && bySlot.has(lightSlot)) {
      pairSlots.set(i, { heavySlot, lightSlot });
    }
  }

  /** Change to (W1 - W2) if pair i's two blades swap slots. */
  function flipDelta(i: number): number {
    const pair = pairSlots.get(i);
    if (!pair) return 0;
    const { heavySlot, lightSlot } = pair;
    const wH = bySlot.get(heavySlot)!.blade.weight_grams ?? 0;
    const wL = bySlot.get(lightSlot)!.blade.weight_grams ?? 0;
    const before = (heavySlot <= half ? wH : -wH) + (lightSlot <= half ? wL : -wL);
    const after = (heavySlot <= half ? wL : -wL) + (lightSlot <= half ? wH : -wH);
    return after - before;
  }

  function evaluate(flipIndices: number[]) {
    const signedDiff = flipIndices.reduce((d, i) => d + flipDelta(i), currentSignedDiff);
    const startHalfIsHeavier = sign === 1 ? signedDiff > 0 : signedDiff < 0;
    const adjustedDiff = Math.abs(Math.abs(signedDiff) - unbalanceValue);
    const meets = startHalfIsHeavier && adjustedDiff >= HPTR_TARGET_DIFF_MIN && adjustedDiff <= HPTR_TARGET_DIFF_MAX;
    return { adjustedDiff, meets };
  }

  function buildSuggestion(flipIndices: number[], usedNearPairs: boolean): SwapSuggestion {
    const { adjustedDiff, meets } = evaluate(flipIndices);
    const flips: PairFlip[] = flipIndices.map((i) => {
      const { heavySlot, lightSlot } = pairSlots.get(i)!;
      return {
        pairIndex: i,
        slotA: heavySlot,
        slotB: lightSlot,
        bladeASerial: bySlot.get(heavySlot)!.blade.serial_number,
        bladeBSerial: bySlot.get(lightSlot)!.blade.serial_number,
      };
    });
    return { flips, resultingDiff: adjustedDiff, meetsTarget: meets, usedNearPairs };
  }

  /** Smallest combination size that reaches the target; closest-to-mid wins ties within that size. */
  function search(eligible: number[], usedNearPairs: boolean): SwapSuggestion | null {
    const sorted = [...eligible].sort((a, b) => a - b);
    const maxSize = Math.min(sorted.length, MAX_COMBO_SIZE);
    for (let size = 1; size <= maxSize; size++) {
      let best: SwapSuggestion | null = null;
      let bestScore = Infinity;
      for (const combo of combinations(sorted, size)) {
        const { adjustedDiff, meets } = evaluate(combo);
        if (!meets) continue;
        const score = Math.abs(adjustedDiff - targetMid);
        if (score < bestScore) {
          bestScore = score;
          best = buildSuggestion(combo, usedNearPairs);
        }
      }
      if (best) return best;
    }
    return null;
  }

  const allPairIndices = [...pairSlots.keys()];
  const farPairs = allPairIndices.filter((i) => i > NEAR_PAIR_COUNT);
  return search(farPairs, false) ?? search(allPairIndices.filter((i) => i > 0), true);
}
