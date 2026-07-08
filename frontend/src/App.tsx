import { useEffect } from "react";
import AppRouter from "@/routes/index";
import { useUIStore } from "@/store/uiStore";

/**
 * Root application component.
 *
 * Responsibilities:
 *  - Apply the persisted theme to <html> on first render (the store's
 *    onRehydrateStorage also handles this, but this is an extra safety net for
 *    the React tree paint).
 *  - Render the router.
 */
export default function App() {
  const theme = useUIStore((s) => s.theme);

  /* Sync theme class whenever the theme value changes */
  useEffect(() => {
    sessionStorage.removeItem("route-error-reload-attempted");
    
    if (theme === "dark") {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [theme]);

  return <AppRouter />;
}
