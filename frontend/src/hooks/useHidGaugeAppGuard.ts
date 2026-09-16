import { useEffect, useRef } from "react";

// A Sylvac DTI gauge paired as a plain Bluetooth HID keyboard (no VMUX2/COM
// port bridge — see RockingCreepPage.tsx) types its reading as raw keystrokes
// into whatever has OS/browser focus, app-wide, with no data channel to
// scope it. RockingCreepPage already routes those keystrokes to the correct
// field while it's open; everywhere else in the app — including the login
// page, which sits outside the authenticated app shell — they must simply
// not land anywhere. This is mounted once at the true app root (not inside
// the router) so it covers every route, including login; it reads
// window.location.pathname fresh on each keystroke instead of depending on
// router context, and steps aside for Rocking & Creep entry, which owns its
// own capture-and-route guard.
//
// Detection is the same inter-keystroke burst-timing heuristic used there
// (<35ms apart): reliably faster than human typing, so normal typing
// elsewhere (search boxes, numeric fields, etc.) is unaffected. This can
// only block within this browser tab — it can't stop a reading typing into
// a different application/window entirely; that requires OS focus to be on
// this tab when the gauge sends.
const HID_FAST_KEY_MS = 35;
const ROCKING_CREEP_PATH = "/rocking-creep";

export function useHidGaugeAppGuard() {
  const lastKeyAtRef = useRef(0);
  const midBurstRef = useRef(false);
  const burstTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (window.location.pathname === ROCKING_CREEP_PATH) return; // that page guards itself

      const now = performance.now();
      const dt = now - lastKeyAtRef.current;
      lastKeyAtRef.current = now;

      const isBurstChar = /^[0-9+\-.]$/.test(e.key) || e.key === "Enter";
      if (!isBurstChar) return;

      if (midBurstRef.current || dt < HID_FAST_KEY_MS) {
        e.preventDefault();
        e.stopPropagation();
        midBurstRef.current = true;
        if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
        burstTimerRef.current = setTimeout(() => {
          midBurstRef.current = false;
        }, 120);
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
    };
  }, []);
}
