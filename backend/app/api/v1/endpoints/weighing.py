"""
Weighing machine endpoints.

POST /weighing/push  — receive a weight reading from the Windows-side bridge script
WS   /weighing/ws   — stream live weight readings to connected browser clients

Architecture:
  weighing_machine.py (Windows, reads COM6)
    → POST /api/v1/weighing/push  {"value": 123.45}
    → backend publishes to a Redis channel
    → every uvicorn worker's open WebSocket connections receive it
    → browser auto-fills weight field

Broadcast goes through Redis pub/sub rather than an in-memory set: the
backend runs multiple uvicorn worker processes (see backend/Dockerfile,
--workers 4), each with its own separate Python memory space. A WebSocket
connection is pinned to whichever worker accepted it, but POST /push can
land on any worker — an in-memory set only reaches subscribers in that same
worker, so most pushes would silently reach zero clients. Redis pub/sub
fans out to every worker's listeners regardless of which one received the
push.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.security import decode_token

logger = structlog.get_logger(__name__)
router = APIRouter()

_CHANNEL = "weighing:broadcast"


# ─── POST /push ───────────────────────────────────────────────────────────────

class WeightReading(BaseModel):
    value: float


@router.post("/push", status_code=200)
async def push_weight(body: WeightReading, request: Request) -> dict[str, Any]:
    """
    Receive a weight reading from the local Windows bridge script and
    publish it for every connected WebSocket client (across all workers)
    to pick up immediately.

    No auth required — this endpoint only accepts connections from localhost
    (enforced at the nginx layer; /api/v1/weighing/push is not exposed to LAN).
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        logger.warning("weight_push_dropped", reason="redis_unavailable", value=body.value)
        return {"ok": False, "value": body.value}

    await redis_client.publish(_CHANNEL, json.dumps({"value": body.value}))
    logger.debug("weight_pushed", value=body.value)
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

    redis_client = getattr(websocket.app.state, "redis", None)
    if redis_client is None:
        await websocket.close(code=1011, reason="Broadcast backend unavailable")
        return

    await websocket.accept()
    await websocket.send_json({"type": "status", "status": "connected"})

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(_CHANNEL)

    async def _send_weights() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await websocket.send_json({"type": "weight", "value": data["value"]})

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
        await pubsub.unsubscribe(_CHANNEL)
        await pubsub.aclose()
        logger.debug("weighing_ws_closed")
