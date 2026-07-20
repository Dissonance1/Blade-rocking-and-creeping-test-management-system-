import type { BladeListItem } from "@/types";

/**
 * LPTR two-stage slot allocation logic — mirrors the shop-floor procedure
 * exactly (see the LPTR slot allocation spec): unlike HPTR (see
 * `hptrBalancing.ts` / `OHSlotAllocationPage.tsx`), LPTR slots are filled in
 * two physical stages because the rotor can only hold half its blades at a
 * time during the first balancing pass.
 *
 * 1. Before any blades are installed, the empty rotor is balanced. The
 *    balancing machine reports an unbalance *position* — always between two
 *    adjacent slots — and an unbalance *value* (grams). `unbalanceSlot` is
 *    the first-named of that pair (e.g. "between slot 35 and 36" -> 35); the
 *    second slot is always `unbalanceSlot + 1` (wrapping `totalSlots` -> 1).
 * 2. Sort all blades by weight descending.
 * 3. The two heaviest blades go to the anchor pair (`unbalanceSlot`, its
 *    neighbor).
 * 4. The opposite slots (45 slots away on the 90-slot rotor) get whichever
 *    two remaining blades are individually closest to a computed target
 *    weight: (anchor pair's combined weight - unbalance value) / 2.
 * 5. Every following pair takes the next two heaviest remaining blades,
 *    placed at the next slot in the chain (stepping by 2 from the second
 *    anchor slot, leaving one slot empty each time) and that slot's
 *    opposite — until 46 blades are placed (Stage 1).
 * 6. Stage 1 is installed and balancing-checked, then physically removed.
 * 7. The remaining 44 blades fill the slots Stage 1 left empty, using the
 *    same "next heaviest pair -> next slot in the complementary chain and
 *    its opposite" rule, starting the chain from `unbalanceSlot` itself
 *    (Stage 2) — no target-weight matching here, that correction only
 *    applies to Stage 1's initial anchor.
 */

export const LPTR_TOTAL_SLOTS = 90;
export const LPTR_STAGE1_COUNT = 46;
export const LPTR_STAGE2_COUNT = 44;
export const LPTR_UNBALANCE_LIMIT_G = 7.1;

export interface LptrAllocationEntry {
  blade: BladeListItem;
  slot: number;
}

/** Opposite slot on the rotor: exactly half the total slots away, wrapping around. */
export function oppositeSlot(slot: number, totalSlots: number = LPTR_TOTAL_SLOTS): number {
  const half = totalSlots / 2;
  return ((slot - 1 + half) % totalSlots) + 1;
}

/** `slot` shifted forward by `delta` positions on the full rotor (1-indexed, wraps). */
function stepSlot(slot: number, delta: number, totalSlots: number): number {
  return (((slot - 1 + delta) % totalSlots) + totalSlots) % totalSlots + 1;
}

function weightOf(blade: BladeListItem): number {
  return blade.weight_grams ?? 0;
}

export interface LptrStage1Result {
  /** The 46 stage-1 blade/slot assignments. */
  entries: LptrAllocationEntry[];
  /** Slot numbers stage 1 occupies — stage 2 fills everything else. */
  usedSlots: Set<number>;
  /** The 44 blades left over for stage 2, still sorted by weight descending. */
  remainingPool: BladeListItem[];
  /** The computed target weight used to pick the anchor's opposite pair. */
  targetWeight: number;
}

/**
 * Steps 2-5: compute the 46-blade stage-1 allocation.
 *
 * `unbalanceSlot` is the first-named slot of the reported unbalance
 * position; its adjacent partner (`unbalanceSlot + 1`, wrapping) is derived
 * automatically since the position is always "between two adjacent slots."
 */
export function computeLptrStage1(
  blades: BladeListItem[],
  unbalanceSlot: number,
  unbalanceValue: number,
  totalSlots: number = LPTR_TOTAL_SLOTS,
  stage1Count: number = LPTR_STAGE1_COUNT
): LptrStage1Result {
  const pool = [...blades].sort((a, b) => weightOf(b) - weightOf(a));
  const slotA = unbalanceSlot;
  const slotB = stepSlot(slotA, 1, totalSlots);

  const entries: LptrAllocationEntry[] = [];
  const usedSlots = new Set<number>();

  // Step 3: two heaviest blades at the anchor pair.
  const heavyA = pool.shift();
  const heavyB = pool.shift();
  if (heavyA) {
    entries.push({ blade: heavyA, slot: slotA });
    usedSlots.add(slotA);
  }
  if (heavyB) {
    entries.push({ blade: heavyB, slot: slotB });
    usedSlots.add(slotB);
  }

  // Step 4: target weight, then the two remaining blades closest to it go
  // to the anchor pair's opposite slots.
  const targetWeight = ((weightOf(heavyA ?? { weight_grams: 0 } as BladeListItem) +
    weightOf(heavyB ?? { weight_grams: 0 } as BladeListItem)) - unbalanceValue) / 2;

  const byCloseness = [...pool].sort(
    (a, b) => Math.abs(weightOf(a) - targetWeight) - Math.abs(weightOf(b) - targetWeight)
  );
  const closest1 = byCloseness[0];
  const closest2 = byCloseness[1];
  if (closest1) pool.splice(pool.indexOf(closest1), 1);
  if (closest2) pool.splice(pool.indexOf(closest2), 1);

  const oppA = oppositeSlot(slotA, totalSlots);
  const oppB = oppositeSlot(slotB, totalSlots);
  if (closest1) {
    entries.push({ blade: closest1, slot: oppA });
    usedSlots.add(oppA);
  }
  if (closest2) {
    entries.push({ blade: closest2, slot: oppB });
    usedSlots.add(oppB);
  }

  // Step 5: continue alternate allocation (leaving one slot empty each
  // time) until stage1Count blades are placed.
  let nextSlot = slotB;
  while (entries.length < stage1Count && pool.length > 0) {
    nextSlot = stepSlot(nextSlot, 2, totalSlots);
    const nextOpp = oppositeSlot(nextSlot, totalSlots);

    const bladeHeavy = pool.shift();
    if (bladeHeavy) {
      entries.push({ blade: bladeHeavy, slot: nextSlot });
      usedSlots.add(nextSlot);
    }
    if (entries.length >= stage1Count) break;

    const bladeOpp = pool.shift();
    if (bladeOpp) {
      entries.push({ blade: bladeOpp, slot: nextOpp });
      usedSlots.add(nextOpp);
    }
  }

  return { entries, usedSlots, remainingPool: pool, targetWeight };
}

/**
 * Step 9: compute the 44-blade stage-2 allocation, filling exactly the
 * slots stage 1 left empty. `remainingPool` is stage 1's leftover blades
 * (already weight-sorted); the chain starts from `unbalanceSlot` itself
 * (the slot stage 1's chain never continued from) rather than its neighbor.
 */
export function computeLptrStage2(
  remainingPool: BladeListItem[],
  unbalanceSlot: number,
  totalSlots: number = LPTR_TOTAL_SLOTS,
  stage2Count: number = LPTR_STAGE2_COUNT
): LptrAllocationEntry[] {
  const pool = [...remainingPool].sort((a, b) => weightOf(b) - weightOf(a));
  const entries: LptrAllocationEntry[] = [];

  let nextSlot = unbalanceSlot;
  while (entries.length < stage2Count && pool.length > 0) {
    nextSlot = stepSlot(nextSlot, 2, totalSlots);
    const nextOpp = oppositeSlot(nextSlot, totalSlots);

    const bladeHeavy = pool.shift();
    if (bladeHeavy) entries.push({ blade: bladeHeavy, slot: nextSlot });
    if (entries.length >= stage2Count) break;

    const bladeOpp = pool.shift();
    if (bladeOpp) entries.push({ blade: bladeOpp, slot: nextOpp });
  }

  return entries;
}

/** Whether a measured unbalance value is within the acceptable limit. */
export function isLptrBalancingPass(
  measuredUnbalance: number,
  limit: number = LPTR_UNBALANCE_LIMIT_G
): boolean {
  return measuredUnbalance <= limit;
}
