"""
DTI (Dial Test Indicator) gauge endpoints.

POST /dti/push  — receive a height-position reading from the Windows-side bridge script
WS   /dti/ws   — stream live DTI readings to connected browser clients

Architecture (two-station deployment):
  Station 1: dti_bridge.py --port COM1 --station 1
    → POST /api/v1/dti/push  {"station": "1", "position": "H1", "value": 12.345}
    → backend routes only to WS subscribers for station "1"

  Station 2: dti_bridge.py --port COM2 --station 2
    → POST /api/v1/dti/push  {"station": "2", "position": "H1", "value": 12.345}
    → backend routes only to WS subscribers for station "2"

  Browser connects: ws://.../dti/ws?token=<jwt>&station=1
    → only receives readings from the gauge on station 1

  Omitting station defaults to "1" for backwards compatibility with single-gauge setups.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from app.core.security import decode_token

logger = structlog.get_logger(__name__)
router = APIRouter()

# ─── In-memory state ─────────────────────────────────────────────────────────
# Subscribers keyed by station; position_count is how many rows the active form has.

_subscribers: dict[str, set[asyncio.Queue[dict]]] = {}
_position_count: int = 4  # updated by frontend when rows are added/removed
_reset_pending: dict[str, bool] = {}  # set by frontend on new blade entry
_cycle_readings: dict[str, dict[str, float]] = {}  # station -> {position: value} captured so far this blade

_POSITION_RE = re.compile(r"^H\d+$")


def _broadcast(station: str, reading: dict) -> None:
    queues = _subscribers.get(station, set())
    dead: set[asyncio.Queue[dict]] = set()
    for q in queues:
        try:
            q.put_nowait(reading)
        except asyncio.QueueFull:
            dead.add(q)
    queues.difference_update(dead)


# ─── POST /push ───────────────────────────────────────────────────────────────

class DtiReading(BaseModel):
    station: str = Field(
        default="1",
        description="Station identifier matching the rig this gauge is attached to (e.g. '1', '2'). Defaults to '1'.",
        examples=["1", "2"],
    )
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


class DtiPositionConfig(BaseModel):
    count: int = Field(..., ge=1, le=30, description="Number of height positions in the active form")


@router.get("/positions")
async def get_position_count() -> dict[str, Any]:
    """Return how many height positions the bridge should cycle through."""
    return {"count": _position_count}


@router.post("/positions", status_code=200)
async def set_position_count(body: DtiPositionConfig) -> dict[str, Any]:
    """Frontend calls this whenever rows are added or removed from the measurement form."""
    global _position_count
    _position_count = body.count
    logger.debug("dti_position_count_updated", count=_position_count)
    return {"count": _position_count}


@router.post("/reset", status_code=200)
async def reset_dti_cycle(station: str = Query(default="1")) -> dict[str, Any]:
    """Frontend calls this when a new blade entry starts — forces bridge back to H1."""
    _reset_pending[station] = True
    _cycle_readings[station] = {}
    logger.debug("dti_reset_requested", station=station)
    return {"ok": True, "station": station}


@router.post("/push", status_code=200)
async def push_dti(body: DtiReading) -> dict[str, Any]:
    """
    Receive a single DTI height-position reading from the local Windows bridge
    script and broadcast it to WebSocket clients subscribed to the same station.
    Response includes next_position so the bridge always cycles the right number
    of positions without needing --positions configured manually.

    No auth required — this endpoint only accepts connections from localhost
    (enforced at the nginx layer; /api/v1/dti/push is not exposed to LAN).
    """
    # If a reset was requested (new blade started), override position to H1
    # regardless of what the bridge sent (bridge may be mid-cycle from last blade)
    if _reset_pending.pop(body.station, False):
        broadcast_pos = "H1"
        next_num = 2 if _position_count > 1 else 1
        _cycle_readings[body.station] = {}
    else:
        broadcast_pos = body.position
        current_num = int(body.position[1:])
        next_num = (current_num % _position_count) + 1

    reading = {"position": broadcast_pos, "value": body.value}
    _cycle_readings.setdefault(body.station, {})[broadcast_pos] = body.value
    _broadcast(body.station, reading)
    next_position = f"H{next_num}"

    subscriber_count = len(_subscribers.get(body.station, set()))
    logger.debug(
        "dti_pushed",
        station=body.station,
        position=body.position,
        value=body.value,
        next_position=next_position,
        position_count=_position_count,
        subscribers=subscriber_count,
    )
    return {
        "ok": True,
        "station": body.station,
        "position": body.position,
        "value": body.value,
        "next_position": next_position,
        "position_count": _position_count,
    }


# ─── WS /ws ───────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def dti_ws(websocket: WebSocket) -> None:
    """
    Stream live DTI gauge readings to the browser for a specific station.

    Auth: pass ?token=<access_token> (same pattern as notifications and weighing WS).
    Station: pass ?station=1 or ?station=2 to match the rig's bridge --station value.
             Defaults to "1" if omitted (backwards-compatible with single-gauge setups).

    Messages sent to client:
      {"type": "status",  "status": "connected", "station": "1"}  — on open
      {"type": "dti",     "position": "H1", "value": 12.345}      — each new reading
      {"type": "ping"}                                              — keepalive every 30 s
    """
    token: str | None = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Authentication token required")
        return

    if decode_token(token) is None:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    station: str = websocket.query_params.get("station", "1")

    await websocket.accept()
    await websocket.send_json({"type": "status", "status": "connected", "station": station})

    # Catch the client up on readings captured for this blade before it connected
    # (server restart, WS reconnect gap, page navigation) — otherwise those readings
    # are lost forever since _broadcast only reaches queues that exist at push time.
    buffered = _cycle_readings.get(station, {})
    for position in sorted(buffered, key=lambda p: int(p[1:])):
        await websocket.send_json({"type": "dti", "position": position, "value": buffered[position]})

    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=20)
    _subscribers.setdefault(station, set()).add(q)

    async def _send_readings() -> None:
        while True:
            reading = await q.get()
            await websocket.send_json({"type": "dti", **reading})
            # Any exception here propagates — gather cancels the other tasks cleanly

    async def _ping() -> None:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})

    async def _receive() -> None:
        while True:
            await websocket.receive_text()
        # WebSocketDisconnect propagates — gather cancels send_readings and ping

    try:
        await asyncio.gather(
            _send_readings(), _ping(), _receive(),
        )
    except (WebSocketDisconnect, Exception):
        pass
    except Exception as exc:
        logger.warning("dti_ws_error", error=str(exc))
    finally:
        _subscribers.get(station, set()).discard(q)
        logger.debug("dti_ws_closed", station=station)
