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
 * 4. The opposite slots (45 slots away on the 90-slot rotor) get a pair of
 *    remaining blades chosen to offset the anchor pair: the first is
 *    whichever blade is individually closest to a computed target weight,
 *    (anchor pair's combined weight - unbalance value) / 2; the second is
 *    whichever remaining blade makes the pair's *combined* weight closest
 *    to the full required total (2x the target weight) — not whichever is
 *    merely next-closest to the target weight alone.
 * 4b. Fallback — 4-blade anchor: sometimes the single blade closest to the
 *    target weight is also the lightest blade left in the whole batch —
 *    there's nothing lighter available to try instead, so the 2-blade
 *    anchor has bottomed out. When that happens — or the operator manually
 *    asks for it — the anchor grows from 2 blades to 4: the next two
 *    heaviest blades go one slot further out on each side
 *    (`unbalanceSlot - 2` and `(unbalanceSlot + 1) + 2`), and all four
 *    opposite slots are filled by sequentially picking the blade closest to
 *    the *remaining* needed average — same technique as step 4, generalized
 *    from 2 picks to 4.
 * 5. Every following pair takes the next two heaviest remaining blades,
 *    placed at the next slot in the chain (stepping by 2 from the
 *    *previous round's opposite slot*, leaving one slot empty each time)
 *    and that slot's opposite — until 46 blades are placed (Stage 1).
 *    E.g. starting from anchor slot 10: 12, 57, 59, 14, 16, 61, 63, 18, 20...
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
  /** The computed target weight used to pick the anchor's opposite pair (per-blade average). */
  targetWeight: number;
  /** Whether the 4-blade anchor fallback (step 4b) was used instead of the normal 2-blade anchor. */
  usedFourBladeAnchor: boolean;
  /** The anchor slots actually used — [slotA, slotB] normally, or 4 slots when the fallback triggers. */
  anchorSlots: number[];
}

/**
 * Sequentially pick `count` blades from `pool` (mutated in place) whose
 * combined weight best matches `requiredSum`: each pick targets whatever
 * average is still needed for the *remaining* picks given what's already
 * been chosen, rather than all picks targeting the same flat average.
 * This is step 4's 2-blade technique generalized to n blades.
 */
function pickClosestToRequiredSum(
  pool: BladeListItem[],
  requiredSum: number,
  count: number
): BladeListItem[] {
  const picks: BladeListItem[] = [];
  let runningSum = 0;
  for (let i = 0; i < count && pool.length > 0; i++) {
    const remaining = count - i;
    const stepTarget = (requiredSum - runningSum) / remaining;
    const sorted = [...pool].sort(
      (a, b) => Math.abs(weightOf(a) - stepTarget) - Math.abs(weightOf(b) - stepTarget)
    );
    const pick = sorted[0]!;
    pool.splice(pool.indexOf(pick), 1);
    runningSum += weightOf(pick);
    picks.push(pick);
  }
  return picks;
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
  stage1Count: number = LPTR_STAGE1_COUNT,
  forceFourBladeAnchor: boolean = false
): LptrStage1Result {
  const pool = [...blades].sort((a, b) => weightOf(b) - weightOf(a));
  const slotA = stepSlot(unbalanceSlot, 0, totalSlots);
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

  // Step 4: target weight — the per-blade average the opposite side needs
  // to hit to offset the anchor pair.
  const targetWeight = ((weightOf(heavyA ?? { weight_grams: 0 } as BladeListItem) +
    weightOf(heavyB ?? { weight_grams: 0 } as BladeListItem)) - unbalanceValue) / 2;

  // Decide whether the normal 2-blade anchor can be matched well enough, or
  // whether step 4b's 4-blade fallback is needed: the single closest blade
  // to the target is also the lightest blade left in the whole batch — i.e.
  // there's nothing lighter to try instead, we've bottomed out.
  const byCloseness = [...pool].sort(
    (a, b) => Math.abs(weightOf(a) - targetWeight) - Math.abs(weightOf(b) - targetWeight)
  );
  const nearest = byCloseness[0];
  const lightestRemaining = pool[pool.length - 1];
  const nearestIsLightestAvailable = !!nearest && !!lightestRemaining && nearest === lightestRemaining;
  const usedFourBladeAnchor = forceFourBladeAnchor || nearestIsLightestAvailable;

  let anchorSlots: number[];
  let cursorStart: number;

  if (!usedFourBladeAnchor) {
    // Step 4: two remaining blades go to the anchor pair's opposite slots
    // — the first is whichever blade is individually closest to the
    // target, the second is whichever remaining blade makes the pair's
    // *combined* weight closest to the required total (2 * targetWeight),
    // not whichever is merely next-closest to the target weight alone.
    const requiredSum = targetWeight * 2;
    const [closest1, closest2] = pickClosestToRequiredSum(pool, requiredSum, 2);

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
    anchorSlots = [slotA, slotB];
    cursorStart = slotB;
  } else {
    // Step 4b: grow the anchor to 4 blades. The 3rd and 4th heaviest
    // blades overall go one slot further out on each side of the original
    // pair, then all 4 opposite slots are filled by sequentially picking
    // whichever blade best matches the average still needed.
    const leftFlank = stepSlot(slotA, -2, totalSlots);
    const rightFlank = stepSlot(slotB, 2, totalSlots);
    const heavyC = pool.shift();
    const heavyD = pool.shift();
    if (heavyC) {
      entries.push({ blade: heavyC, slot: leftFlank });
      usedSlots.add(leftFlank);
    }
    if (heavyD) {
      entries.push({ blade: heavyD, slot: rightFlank });
      usedSlots.add(rightFlank);
    }

    const requiredSum4 = [heavyA, heavyB, heavyC, heavyD].reduce(
      (sum, b) => sum + weightOf(b ?? ({ weight_grams: 0 } as BladeListItem)),
      0
    ) - unbalanceValue;
    const opposites = pickClosestToRequiredSum(pool, requiredSum4, 4);
    const oppositeSlotsForAnchor = [slotA, slotB, leftFlank, rightFlank].map((s) => oppositeSlot(s, totalSlots));
    opposites.forEach((blade, i) => {
      const slot = oppositeSlotsForAnchor[i]!;
      entries.push({ blade, slot });
      usedSlots.add(slot);
    });

    anchorSlots = [slotA, slotB, leftFlank, rightFlank];
    cursorStart = rightFlank;
  }

  // Step 5: continue alternate allocation (leaving one slot empty each
  // time) until stage1Count blades are placed. Each round's chain slot
  // steps by 2 from the previous round's opposite slot, not from the
  // previous chain slot: 12, 57, 59, 14, 16, 61, 63, 18, 20...
  let cursor = cursorStart;
  while (entries.length < stage1Count && pool.length > 0) {
    const nextSlot = stepSlot(cursor, 2, totalSlots);
    const nextOpp = oppositeSlot(nextSlot, totalSlots);
    cursor = nextOpp;

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

  return { entries, usedSlots, remainingPool: pool, targetWeight, usedFourBladeAnchor, anchorSlots };
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

  let cursor = unbalanceSlot;
  while (entries.length < stage2Count && pool.length > 0) {
    const nextSlot = stepSlot(cursor, 2, totalSlots);
    const nextOpp = oppositeSlot(nextSlot, totalSlots);
    cursor = nextOpp;

    const bladeHeavy = pool.shift();
    if (bladeHeavy) entries.push({ blade: bladeHeavy, slot: nextSlot });
    if (entries.length >= stage2Count) break;

    const bladeOpp = pool.shift();
    if (bladeOpp) entries.push({ blade: bladeOpp, slot: nextOpp });
  }

  return entries;
}

/**
 * Manual balancing swap: exchange which blade occupies each of two slots.
 * Slot numbers themselves never change, only the blade assigned to them.
 * Mirrors `hptrBalancing.ts`'s `swapBladesBetweenSlots` — same entry shape.
 */
export function swapBladesBetweenSlots(
  entries: LptrAllocationEntry[],
  slotA: number,
  slotB: number
): LptrAllocationEntry[] {
  return entries.map((entry) => {
    if (entry.slot === slotA) return { ...entry, slot: slotB };
    if (entry.slot === slotB) return { ...entry, slot: slotA };
    return entry;
  });
}

/** Whether a measured unbalance value is within the acceptable limit. */
export function isLptrBalancingPass(
  measuredUnbalance: number,
  limit: number = LPTR_UNBALANCE_LIMIT_G
): boolean {
  return measuredUnbalance <= limit;
}
