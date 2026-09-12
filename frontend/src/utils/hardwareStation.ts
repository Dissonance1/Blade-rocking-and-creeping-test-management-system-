/**
 * Which physical hardware station (weighing scale / DTI gauge) this browser
 * should listen to. Distinguishes two independently-wired instruments that
 * both push readings to the same central backend — e.g. the OH PC's own
 * scale/gauge vs. a second PC's own scale/gauge (see CLAUDE.md's "Secondary
 * Hardware Stations"). Both `/weighing/ws` and `/dti/ws` scope broadcasts by
 * this value; without it, every browser on every PC receives every PC's
 * readings.
 *
 * Read once from the URL (`?station=2`) rather than a build-time env var,
 * since one frontend build is served to every station (see CLAUDE.md) — a
 * build-time flag can't distinguish which physical PC a given browser is
 * running on. Bookmark the station-specific URL on each PC that has its own
 * scale/gauge; every other station's bookmark is unaffected since this
 * defaults to "1", matching the bridge scripts' own `--station 1` default.
 */
export function getHardwareStation(): string {
  return new URLSearchParams(window.location.search).get("station") ?? "1";
}
