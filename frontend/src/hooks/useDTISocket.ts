import { useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/store/authStore";

export interface DTIReading {
  position: string;
  value: number;
  capturedAt: Date;
}

interface WsMessage {
  type: "dti" | "status" | "ping";
  position?: string;
  value?: number;
}

const RECONNECT_DELAY_MS = 3000;
const AUTH_ERROR_CODE    = 4001; // backend sends this on expired/invalid token — don't retry

/**
 * Connects to /api/v1/dti/ws and streams live height readings from the gauge bridge.
 * Auto-reconnects after backend restarts (3 s delay). Does not retry on auth errors.
 */
export function useDTISocket(station: string = "1") {
  const [lastReading, setLastReading] = useState<DTIReading | null>(null);
  const [connected, setConnected]     = useState(false);
  const accessToken = useAuthStore((s) => s.accessToken);
  const wsRef       = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!accessToken) return;

    let unmounted  = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (unmounted) return;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host     = window.location.host;
      const url      = `${protocol}//${host}/api/v1/dti/ws?token=${accessToken}&station=${station}`;

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onclose = (ev) => {
        setConnected(false);
        wsRef.current = null;
        // Don't retry on auth errors — token must be refreshed first
        if (!unmounted && ev.code !== AUTH_ERROR_CODE) {
          retryTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = () => setConnected(false);

      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data as string);
          if (msg.type === "dti" && msg.position && msg.value != null) {
            setLastReading({
              position:   msg.position.toUpperCase(),
              value:      msg.value,
              capturedAt: new Date(),
            });
          }
        } catch {
          // ignore malformed frames
        }
      };
    };

    connect();

    return () => {
      unmounted = true;
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [accessToken, station]);

  return { lastReading, connected };
}
