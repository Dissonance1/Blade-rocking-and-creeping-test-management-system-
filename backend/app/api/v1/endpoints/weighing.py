"""
Weighing machine endpoints.

POST /weighing/push  — receive a weight reading from the Windows-side bridge script
WS   /weighing/ws   — stream live weight readings to connected browser clients

Architecture:
  weighing_machine.py (Windows, reads COM6)
    → POST /api/v1/weighing/push  {"value": 123.45}
    → backend broadcasts to all open WebSocket connections
    → browser auto-fills weight field
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.security import decode_token

logger = structlog.get_logger(__name__)
router = APIRouter()

# ─── In-memory broadcaster ────────────────────────────────────────────────────
# Each open WebSocket connection registers a queue here.
# POST /push puts a value into every queue → all clients get the reading instantly.

_subscribers: set[asyncio.Queue[float]] = set()


def _broadcast(value: float) -> None:
    dead: set[asyncio.Queue[float]] = set()
    for q in _subscribers:
        try:
            q.put_nowait(value)
        except asyncio.QueueFull:
            dead.add(q)
    _subscribers.difference_update(dead)


# ─── POST /push ───────────────────────────────────────────────────────────────

class WeightReading(BaseModel):
    value: float


@router.post("/push", status_code=200)
async def push_weight(body: WeightReading) -> dict[str, Any]:
    """
    Receive a weight reading from the local Windows bridge script and
    broadcast it to all connected WebSocket clients immediately.

    No auth required — this endpoint only accepts connections from localhost
    (enforced at the nginx layer; /api/v1/weighing/push is not exposed to LAN).
    """
    _broadcast(body.value)
    logger.debug("weight_pushed", value=body.value, subscribers=len(_subscribers))
    return {"ok": True, "value": body.value}


# ─── WS /ws ───────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def weighing_ws(websocket: WebSocket) -> None:
    """
    Stream live weight readings to the browser.

    Auth: pass ?token=<access_token> (same pattern as notifications WS).

    Messages sent to client:
      {"type": "status", "status": "connected"}   — on open
      {"type": "weight", "value": 123.45}          — each new reading
      {"type": "ping"}                             — keepalive every 30 s
    """
    token: str | None = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Authentication token required")
        return

    if decode_token(token) is None:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()
    await websocket.send_json({"type": "status", "status": "connected"})

    q: asyncio.Queue[float] = asyncio.Queue(maxsize=20)
    _subscribers.add(q)

    async def _send_weights() -> None:
        while True:
            value = await q.get()
            await websocket.send_json({"type": "weight", "value": value})

    async def _ping() -> None:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})

    async def _receive() -> None:
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    try:
        await asyncio.gather(
            _send_weights(), _ping(), _receive(),
            return_exceptions=True,
        )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("weighing_ws_error", error=str(exc))
    finally:
        _subscribers.discard(q)
        logger.debug("weighing_ws_closed")
