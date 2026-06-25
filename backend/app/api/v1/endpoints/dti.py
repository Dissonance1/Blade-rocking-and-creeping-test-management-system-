"""
DTI (Dial Test Indicator) gauge endpoints.

POST /dti/push  — receive a height-position reading from the Windows-side bridge script
WS   /dti/ws   — stream live DTI readings to connected browser clients

Architecture:
  dti_bridge.py (Windows, reads COM7)
    → POST /api/v1/dti/push  {"position": "H1", "value": 12.345}
    → backend broadcasts to all open WebSocket connections
    → browser auto-fills the corresponding height field in the measurement form
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from app.core.security import decode_token

logger = structlog.get_logger(__name__)
router = APIRouter()

# ─── In-memory broadcaster ────────────────────────────────────────────────────
# Each open WebSocket connection registers a queue here.
# POST /push puts a reading into every queue → all browser tabs update instantly.

_subscribers: set[asyncio.Queue[dict]] = set()

_POSITION_RE = re.compile(r"^H\d+$")


def _broadcast(reading: dict) -> None:
    dead: set[asyncio.Queue[dict]] = set()
    for q in _subscribers:
        try:
            q.put_nowait(reading)
        except asyncio.QueueFull:
            dead.add(q)
    _subscribers.difference_update(dead)


# ─── POST /push ───────────────────────────────────────────────────────────────

class DtiReading(BaseModel):
    position: str = Field(
        ...,
        description="Height-position label, must match H<n> pattern (e.g. H1, H2, H3, H4)",
        examples=["H1", "H2", "H3", "H4"],
    )
    value: float = Field(
        ...,
        description="DTI reading in millimetres",
        examples=[12.345],
    )

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: str) -> str:
        if not _POSITION_RE.match(v):
            raise ValueError(
                f"Invalid DTI position '{v}'. Must match H<n> pattern (H1, H2, H3, …)."
            )
        return v


@router.post("/push", status_code=200)
async def push_dti(body: DtiReading) -> dict[str, Any]:
    """
    Receive a single DTI height-position reading from the local Windows bridge
    script and broadcast it to all connected WebSocket clients immediately.

    No auth required — this endpoint only accepts connections from localhost
    (enforced at the nginx layer; /api/v1/dti/push is not exposed to LAN).
    """
    reading = {"position": body.position, "value": body.value}
    _broadcast(reading)
    logger.debug("dti_pushed", position=body.position, value=body.value, subscribers=len(_subscribers))
    return {"ok": True, "position": body.position, "value": body.value}


# ─── WS /ws ───────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def dti_ws(websocket: WebSocket) -> None:
    """
    Stream live DTI gauge readings to the browser.

    Auth: pass ?token=<access_token> (same pattern as notifications and weighing WS).

    Messages sent to client:
      {"type": "status",  "status": "connected"}        — on open
      {"type": "dti",     "position": "H1", "value": 12.345}  — each new reading
      {"type": "ping"}                                   — keepalive every 30 s
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

    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=20)
    _subscribers.add(q)

    async def _send_readings() -> None:
        while True:
            reading = await q.get()
            await websocket.send_json({"type": "dti", **reading})

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
            _send_readings(), _ping(), _receive(),
            return_exceptions=True,
        )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("dti_ws_error", error=str(exc))
    finally:
        _subscribers.discard(q)
        logger.debug("dti_ws_closed")
