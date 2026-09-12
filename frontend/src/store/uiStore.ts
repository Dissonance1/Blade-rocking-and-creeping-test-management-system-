import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UIState {
  sidebarCollapsed: boolean;
  theme: "light" | "dark";
  hardwareStation: string;
  toggleSidebar: () => void;
  setSidebarCollapsed: (v: boolean) => void;
  setTheme: (t: "light" | "dark") => void;
  toggleTheme: () => void;
  setHardwareStation: (s: string) => void;
}

function applyTheme(theme: "light" | "dark") {
  if (theme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

function initialHardwareStation(): string {
  return new URLSearchParams(window.location.search).get("station") ?? "1";
}

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      sidebarCollapsed: false,
      theme: "light",
      hardwareStation: initialHardwareStation(),

      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      setSidebarCollapsed: (v: boolean) => set({ sidebarCollapsed: v }),

      setTheme: (t: "light" | "dark") => {
        applyTheme(t);
        set({ theme: t });
      },

      toggleTheme: () => {
        const next = get().theme === "light" ? "dark" : "light";
        applyTheme(next);
        set({ theme: next });
      },

      setHardwareStation: (s: string) => set({ hardwareStation: s }),
    }),
    {
      name: "blade-ui",
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        theme: state.theme,
        hardwareStation: state.hardwareStation,
      }),
      // An explicit ?station= in the URL (a bookmark set up on this PC) wins
      // over whatever was last persisted — otherwise a bookmark meant to pin
      // this browser to a station would be silently ignored after the first
      // visit.
      merge: (persistedState, currentState) => {
        const merged = { ...currentState, ...(persistedState as Partial<UIState>) };
        const urlStation = new URLSearchParams(window.location.search).get("station");
        if (urlStation) {
          merged.hardwareStation = urlStation;
        }
        return merged;
      },
      onRehydrateStorage: () => (state) => {
        if (state) {
          applyTheme(state.theme);
        }
      },
    }
  )
);
