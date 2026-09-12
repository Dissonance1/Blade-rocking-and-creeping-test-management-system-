"""
Weighing machine endpoints.

POST /weighing/push  — receive a weight reading from the Windows-side bridge script
WS   /weighing/ws   — stream live weight readings to connected browser clients

Architecture (mirrors dti.py's station scoping):
  Station 1 (e.g. the OH PC's own scale): weighing_bridge.py --station 1
    → POST /api/v1/weighing/push  {"station": "1", "value": 123.45}
    → backend routes only to WS subscribers for station "1"

  Station 2 (e.g. a second PC's own scale, see CLAUDE.md's "Secondary
  Hardware Stations"): weighing_bridge.py --station 2 --server <OH PC>
    → POST /api/v1/weighing/push  {"station": "2", "value": 123.45}
    → backend routes only to WS subscribers for station "2"

  Browser connects: ws://.../weighing/ws?token=<jwt>&station=2
    → only receives readings from the scale on station 2

  Omitting station defaults to "1" for backwards compatibility with
  single-scale setups — this used to be a single global channel with no
  station concept at all, which silently broke the moment a second PC's
  weighing bridge started pushing to the same central backend: every
  browser, regardless of which PC it was open on, received every scale's
  readings.

Broadcast goes through Redis pub/sub rather than an in-memory set: the
backend runs multiple uvicorn worker processes (see backend/Dockerfile,
--workers 4), each with its own separate Python memory space. A WebSocket
connection is pinned to whichever worker accepted it, but POST /push can
land on any worker — an in-memory set only reaches subscribers in that same
worker, so most pushes would silently reach zero clients. Redis pub/sub
fans out to every worker's listeners regardless of which one received the
push.
"""

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.core.security import decode_token
from app.middleware.rate_limit import rate_limit_hardware_bridge

logger = structlog.get_logger(__name__)
router = APIRouter()

_CHANNEL_FMT = "weighing:broadcast:{station}"


# ─── POST /push ───────────────────────────────────────────────────────────────

class WeightReading(BaseModel):
    value: float
    station: str = Field(
        default="1",
        description="Station identifier matching the PC/rig this scale is attached to (e.g. '1', '2'). Defaults to '1'.",
        examples=["1", "2"],
    )


@router.post("/push", status_code=200)
@rate_limit_hardware_bridge()
async def push_weight(body: WeightReading, request: Request, response: Response) -> dict[str, Any]:
    """
    Receive a weight reading from the local Windows bridge script and
    publish it only to WebSocket clients subscribed to the same station
    (across all workers).

    No auth required — trusted the same way the DTI push endpoint is (see
    dti.py): both are internal, bridge-only endpoints on the private LAN,
    not something a browser calls.

    `response: Response` is required by the @rate_limit_hardware_bridge
    decorator — slowapi injects rate-limit headers into it since this
    endpoint returns a plain dict rather than a Response object.
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        logger.warning("weight_push_dropped", reason="redis_unavailable", value=body.value, station=body.station)
        return {"ok": False, "value": body.value, "station": body.station}

    await redis_client.publish(_CHANNEL_FMT.format(station=body.station), json.dumps({"value": body.value}))
    logger.debug("weight_pushed", value=body.value, station=body.station)
    return {"ok": True, "value": body.value, "station": body.station}


# ─── WS /ws ───────────────────────────────────────────────────────────────────

async def _ws_send_weights(websocket: WebSocket, pubsub) -> None:
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        data = json.loads(message["data"])
        await websocket.send_json({"type": "weight", "value": data["value"]})


async def _ws_ping(websocket: WebSocket) -> None:
    while True:
        await asyncio.sleep(30)
        await websocket.send_json({"type": "ping"})


async def _ws_receive(websocket: WebSocket) -> None:
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


@router.websocket("/ws")
async def weighing_ws(websocket: WebSocket) -> None:
    """
    Stream live weight readings to the browser for a specific station.

    Auth: pass ?token=<access_token> (same pattern as notifications WS).
    Station: pass ?station=1 or ?station=2 to match the scale's bridge
             --station value. Defaults to "1" if omitted (backwards-
             compatible with single-scale setups).

    Messages sent to client:
      {"type": "status", "status": "connected", "station": "1"}  — on open
      {"type": "weight", "value": 123.45}                        — each new reading
      {"type": "ping"}                                           — keepalive every 30 s
    """
    token: str | None = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Authentication token required")
        return

    if decode_token(token) is None:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    station: str = websocket.query_params.get("station", "1")

    redis_client = getattr(websocket.app.state, "redis", None)
    if redis_client is None:
        await websocket.close(code=1011, reason="Broadcast backend unavailable")
        return

    await websocket.accept()
    await websocket.send_json({"type": "status", "status": "connected", "station": station})

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(_CHANNEL_FMT.format(station=station))

    try:
        await asyncio.gather(
            _ws_send_weights(websocket, pubsub), _ws_ping(websocket), _ws_receive(websocket),
            return_exceptions=True,
        )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("weighing_ws_error", error=str(exc))
    finally:
        await pubsub.unsubscribe(_CHANNEL_FMT.format(station=station))
        await pubsub.aclose()
        logger.debug("weighing_ws_closed", station=station)
