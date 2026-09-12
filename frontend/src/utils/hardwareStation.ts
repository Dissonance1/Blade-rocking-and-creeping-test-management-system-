import { useUIStore } from "@/store/uiStore";

/**
 * Which physical hardware station (weighing scale / DTI gauge) this browser
 * should listen to. Distinguishes two independently-wired instruments that
 * both push readings to the same central backend — e.g. the OH PC's own
 * scale/gauge vs. a second PC's own scale/gauge (see CLAUDE.md's "Secondary
 * Hardware Stations"). Both `/weighing/ws` and `/dti/ws` scope broadcasts by
 * this value; without it, every browser on every PC receives every PC's
 * readings.
 *
 * Backed by `useUIStore` (persisted to localStorage) so it can be changed at
 * runtime from the station picker in the navbar, not just bootstrapped once
 * from `?station=2` in a bookmark. The URL param still seeds/overrides the
 * value on load (see uiStore's `merge`), so existing per-PC bookmarks keep
 * working unchanged; the picker is what lets a PC be switched without having
 * to edit its bookmark.
 */
export function useHardwareStation(): string {
  return useUIStore((s) => s.hardwareStation);
}

/** Non-reactive read, for call sites outside a React component. */
export function getHardwareStation(): string {
  return useUIStore.getState().hardwareStation;
}
