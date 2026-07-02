import { useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/store/authStore";

export interface WeightReading {
  value: number;
  capturedAt: Date;
}

interface WsMessage {
  type: "weight" | "status" | "ping";
  value?: number;
  status?: string;
}

/**
 * Connects to /api/v1/weighing/ws and streams live weight readings
 * from the iScale i-04 bridge running on the Assembly PC.
 *
 * Returns:
 *  - currentReading: latest captured reading (null until first measurement arrives)
 *  - connected: true while WebSocket is open
 *  - clearReading: reset currentReading to null (call after capturing for a blade)
 */
export function useWeighingSocket() {
  const [currentReading, setCurrentReading] = useState<WeightReading | null>(null);
  const [connected, setConnected] = useState(false);
  const accessToken = useAuthStore((s) => s.accessToken);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!accessToken) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const url = `${protocol}//${host}/api/v1/weighing/ws?token=${accessToken}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data as string);
        if (msg.type === "weight" && msg.value != null) {
          setCurrentReading({ value: msg.value, capturedAt: new Date() });
        }
      } catch {
        // ignore malformed frames
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [accessToken]);

  const clearReading = () => setCurrentReading(null);

  return { currentReading, connected, clearReading };
}
