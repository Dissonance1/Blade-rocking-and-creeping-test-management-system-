import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/store/authStore";

export interface WeightReading {
  value: number;
  capturedAt: Date;
}

export type ScaleStatus = "idle" | "connecting" | "connected" | "disconnected";

interface WsMessage {
  type: "weight" | "status" | "ping";
  value?: number;
  status?: string;
}

/**
 * Connects to /api/v1/weighing/ws and streams live weight readings from the
 * iScale i-04 bridge. Single shared socket — mount this once per page (e.g.
 * at the grid-shell level), not once per row.
 *
 * Returns:
 *  - currentReading: latest captured reading (null until first measurement, or after clearReading()/while locked)
 *  - status: connection lifecycle state, with automatic reconnect on drop
 *  - connected: convenience boolean, `status === "connected"`
 *  - locked / toggleLock: freeze the current reading (ignore incoming weight updates) so an
 *    operator can hold a value steady before it's applied to a row
 *  - clearReading: reset currentReading to null (call after a row has consumed a reading)
 */
export function useWeighingSocket() {
  const [currentReading, setCurrentReading] = useState<WeightReading | null>(null);
  const [status, setStatus] = useState<ScaleStatus>("idle");
  const [locked, setLocked] = useState(false);
  const lockedRef = useRef(false);
  const statusRef = useRef<ScaleStatus>("idle");
  const accessToken = useAuthStore((s) => s.accessToken);
  const wsRef = useRef<WebSocket | null>(null);

  const toggleLock = useCallback(() => {
    lockedRef.current = !lockedRef.current;
    setLocked(lockedRef.current);
  }, []);

  useEffect(() => {
    if (!accessToken) return undefined;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const url = `${protocol}//${host}/api/v1/weighing/ws?token=${accessToken}`;

    let alive = true;
    let ws: WebSocket;

    function connect() {
      statusRef.current = "connecting";
      setStatus("connecting");
      ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        statusRef.current = "connected";
        setStatus("connected");
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data as string) as WsMessage;
          if (msg.type === "status") {
            if (msg.status === "unavailable") {
              statusRef.current = "idle";
              setStatus("idle");
              ws.close();
            } else {
              const s = (msg.status as ScaleStatus) ?? "idle";
              statusRef.current = s;
              setStatus(s);
            }
          } else if (msg.type === "weight" && msg.value != null) {
            if (!lockedRef.current) {
              setCurrentReading({ value: msg.value, capturedAt: new Date() });
            }
          } else if (msg.type === "ping") {
            ws.send(JSON.stringify({ type: "pong" }));
          }
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        if (!alive) return;
        statusRef.current = "disconnected";
        setStatus("disconnected");
        setTimeout(() => {
          if (alive) connect();
        }, 5000);
      };

      ws.onerror = () => {
        // onclose fires right after onerror — reconnect is handled there.
      };
    }

    connect();

    return () => {
      alive = false;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [accessToken]);

  const clearReading = useCallback(() => setCurrentReading(null), []);

  return {
    currentReading,
    status,
    connected: status === "connected",
    locked,
    toggleLock,
    clearReading,
  };
}
