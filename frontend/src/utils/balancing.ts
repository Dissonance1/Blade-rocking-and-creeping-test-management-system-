import type { BladeListItem } from "@/types";

/** LPTR balancing algorithm — mirrors the backend's heavy/light interleave logic. */

export interface PreviewRow {
  blade: BladeListItem;
  slot: number;
}

export function computeBalancedSlots(
  blades: BladeListItem[],
  imbalanceSlot: number,
  totalSlots: number
): PreviewRow[] {
  const sorted = [...blades].sort(
    (a, b) => (b.static_moment_gcm ?? 0) - (a.static_moment_gcm ?? 0)
  );
  const half = Math.floor(sorted.length / 2);
  const interleaved = [...sorted.slice(0, half), ...sorted.slice(half).reverse()];
  const K = imbalanceSlot;
  const N = totalSlots;
  return interleaved.map((blade, i) => ({
    blade,
    slot: ((K - 1 + i) % N) + 1,
  }));
}
