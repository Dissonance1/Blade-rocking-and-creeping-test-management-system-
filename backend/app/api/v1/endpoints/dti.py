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

All shared state (position count, pending resets, in-progress cycle readings,
and the broadcast itself) lives in Redis, not process memory: the backend
runs multiple uvicorn worker processes (see backend/Dockerfile, --workers 4),
each with its own separate memory space. A WebSocket connection is pinned to
whichever worker accepted it, but POST /push, /positions, and /reset can each
land on any worker — in-memory state only reaches the worker that handled a
given request, so cross-worker state (like "did the frontend just reset this
station") and cross-worker broadcast (delivering a reading to whichever
worker holds the browser's WS) would otherwise be lost most of the time.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import structlog
from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from app.core.security import decode_token

logger = structlog.get_logger(__name__)
router = APIRouter()

_DEFAULT_POSITION_COUNT = 4
_POSITION_COUNT_KEY = "dti:position_count"
_RESET_KEY_FMT = "dti:reset_pending:{station}"
_CYCLE_KEY_FMT = "dti:cycle:{station}"
_CHANNEL_FMT = "dti:broadcast:{station}"

_POSITION_RE = re.compile(r"^H\d+$")


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
async def get_position_count(request: Request) -> dict[str, Any]:
    """Return how many height positions the bridge should cycle through."""
    redis_client = getattr(request.app.state, "redis", None)
    count = _DEFAULT_POSITION_COUNT
    if redis_client is not None:
        raw = await redis_client.get(_POSITION_COUNT_KEY)
        if raw is not None:
            count = int(raw)
    return {"count": count}


@router.post("/positions", status_code=200)
async def set_position_count(body: DtiPositionConfig, request: Request) -> dict[str, Any]:
    """Frontend calls this whenever rows are added or removed from the measurement form."""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        await redis_client.set(_POSITION_COUNT_KEY, body.count)
    logger.debug("dti_position_count_updated", count=body.count)
    return {"count": body.count}


@router.post("/reset", status_code=200)
async def reset_dti_cycle(request: Request, station: str = Query(default="1")) -> dict[str, Any]:
    """Frontend calls this when a new blade entry starts — forces bridge back to H1."""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        await redis_client.set(_RESET_KEY_FMT.format(station=station), "1")
        await redis_client.delete(_CYCLE_KEY_FMT.format(station=station))
    logger.debug("dti_reset_requested", station=station)
    return {"ok": True, "station": station}


@router.post("/push", status_code=200)
async def push_dti(body: DtiReading, request: Request) -> dict[str, Any]:
    """
    Receive a single DTI height-position reading from the local Windows bridge
    script and broadcast it to WebSocket clients subscribed to the same station.
    Response includes next_position so the bridge always cycles the right number
    of positions without needing --positions configured manually.

    No auth required — this endpoint only accepts connections from localhost
    (enforced at the nginx layer; /api/v1/dti/push is not exposed to LAN).
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        logger.warning("dti_push_dropped", reason="redis_unavailable", station=body.station)
        return {"ok": False, "station": body.station}

    position_count = _DEFAULT_POSITION_COUNT
    raw_count = await redis_client.get(_POSITION_COUNT_KEY)
    if raw_count is not None:
        position_count = int(raw_count)

    cycle_key = _CYCLE_KEY_FMT.format(station=body.station)

    # If a reset was requested (new blade started), override position to H1
    # regardless of what the bridge sent (bridge may be mid-cycle from last blade)
    reset_flag = await redis_client.getdel(_RESET_KEY_FMT.format(station=body.station))
    if reset_flag:
        broadcast_pos = "H1"
        next_num = 2 if position_count > 1 else 1
        await redis_client.delete(cycle_key)
    else:
        broadcast_pos = body.position
        current_num = int(body.position[1:])
        next_num = (current_num % position_count) + 1

    reading = {"position": broadcast_pos, "value": body.value}
    await redis_client.hset(cycle_key, broadcast_pos, body.value)
    await redis_client.publish(_CHANNEL_FMT.format(station=body.station), json.dumps(reading))
    next_position = f"H{next_num}"

    logger.debug(
        "dti_pushed",
        station=body.station,
        position=body.position,
        value=body.value,
        next_position=next_position,
        position_count=position_count,
    )
    return {
        "ok": True,
        "station": body.station,
        "position": body.position,
        "value": body.value,
        "next_position": next_position,
        "position_count": position_count,
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

    Query param `replay` (default "true"): whether to catch the client up on
    readings already buffered for this station before subscribing to live
    pushes. Multi-position height-measurement forms want this (recovering
    readings taken during a reconnect gap). Single-shot capture flows (e.g.
    Rocking & Creep, where any "dti" message is treated as a brand-new button
    press) must pass replay=false — otherwise a reconnect (page refresh, wifi
    blip, server restart) replays old cached values and they get silently
    captured as if the gauge had just been pressed.
    """
    token: str | None = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Authentication token required")
        return

    if decode_token(token) is None:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    station: str = websocket.query_params.get("station", "1")
    replay: bool = websocket.query_params.get("replay", "true").lower() != "false"

    redis_client = getattr(websocket.app.state, "redis", None)
    if redis_client is None:
        await websocket.close(code=1011, reason="Broadcast backend unavailable")
        return

    await websocket.accept()
    await websocket.send_json({"type": "status", "status": "connected", "station": station})

    # Catch the client up on readings captured for this blade before it connected
    # (server restart, WS reconnect gap, page navigation) — otherwise those readings
    # would be lost since the pub/sub channel only reaches subscribers listening
    # at publish time. Skipped when replay=false (single-shot capture flows).
    if replay:
        buffered = await redis_client.hgetall(_CYCLE_KEY_FMT.format(station=station))
        for position in sorted(buffered, key=lambda p: int(p[1:])):
            await websocket.send_json({"type": "dti", "position": position, "value": float(buffered[position])})

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(_CHANNEL_FMT.format(station=station))

    async def _send_readings() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            reading = json.loads(message["data"])
            await websocket.send_json({"type": "dti", **reading})

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
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("dti_ws_error", error=str(exc))
    finally:
        await pubsub.unsubscribe(_CHANNEL_FMT.format(station=station))
        await pubsub.aclose()
        logger.debug("dti_ws_closed", station=station)
