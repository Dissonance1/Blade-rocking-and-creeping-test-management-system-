"""
WebSocket-based real-time notification manager.

Manages per-user WebSocket connections, supporting multi-tab scenarios
where a single user may hold multiple concurrent connections.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketState

if TYPE_CHECKING:
    from app.models.user import User

logger = structlog.get_logger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections grouped by user_id.

    Supports multi-tab / multi-device usage: a single user may have
    several concurrent WebSocket connections.  All per-user connections
    receive the same messages; if one connection is broken it is pruned
    transparently.
    """

    def __init__(self) -> None:
        # user_id -> list of active WebSocket connections
        self.active_connections: dict[UUID, list[WebSocket]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket, user_id: UUID) -> None:
        """Accept and register a new WebSocket connection for *user_id*."""
        await websocket.accept()
        self.active_connections[user_id].append(websocket)
        logger.info(
            "websocket_connected",
            user_id=str(user_id),
            total_connections=len(self.active_connections[user_id]),
        )

    async def disconnect(self, websocket: WebSocket, user_id: UUID) -> None:
        """Remove *websocket* from the registry for *user_id*."""
        connections = self.active_connections.get(user_id, [])
        if websocket in connections:
            connections.remove(websocket)
            logger.info(
                "websocket_disconnected",
                user_id=str(user_id),
                remaining_connections=len(connections),
            )
        # Clean up empty lists to avoid unbounded memory growth.
        if not connections:
            self.active_connections.pop(user_id, None)

    # ------------------------------------------------------------------
    # Sending helpers
    # ------------------------------------------------------------------

    async def send_to_user(self, user_id: UUID, message: dict) -> None:
        """
        Send *message* (serialised as JSON) to **all** connections held
        by *user_id*.  Broken connections are pruned automatically.
        """
        connections = list(self.active_connections.get(user_id, []))
        if not connections:
            logger.debug("send_to_user_no_connections", user_id=str(user_id))
            return

        dead: list[WebSocket] = []
        for ws in connections:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
                else:
                    dead.append(ws)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "websocket_send_failed",
                    user_id=str(user_id),
                    error=str(exc),
                )
                dead.append(ws)

        for ws in dead:
            await self.disconnect(ws, user_id)

    async def broadcast(self, message: dict) -> None:
        """
        Send *message* to **every** connected user across all connections.
        Broken connections are pruned transparently.
        """
        # Snapshot current user set to avoid mutation during iteration.
        user_ids = list(self.active_connections.keys())
        for user_id in user_ids:
            await self.send_to_user(user_id, message)

    async def broadcast_to_role(
        self,
        role: str,
        message: dict,
        all_users: list[User],
    ) -> None:
        """
        Send *message* only to users whose ``role`` attribute matches
        *role*.  *all_users* is a flat list of :class:`User` ORM objects
        (typically fetched from the database before calling this method).

        Only users who currently have an active WebSocket connection
        receive the message.
        """
        target_user_ids: list[UUID] = [
            user.id for user in all_users if getattr(user, "role", None) == role
        ]

        if not target_user_ids:
            logger.debug("broadcast_to_role_no_targets", role=role)
            return

        logger.info(
            "broadcast_to_role",
            role=role,
            target_count=len(target_user_ids),
        )
        for user_id in target_user_ids:
            await self.send_to_user(user_id, message)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def connection_count(self) -> int:
        """Return the total number of open WebSocket connections."""
        return sum(len(conns) for conns in self.active_connections.values())

    def user_connection_count(self, user_id: UUID) -> int:
        """Return the number of open connections for a specific user."""
        return len(self.active_connections.get(user_id, []))


# ---------------------------------------------------------------------------
# Module-level singleton – import this throughout the application.
# ---------------------------------------------------------------------------
notification_manager: ConnectionManager = ConnectionManager()
