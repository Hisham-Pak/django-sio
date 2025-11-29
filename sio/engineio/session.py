from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from .constants import (
    MAX_PAYLOAD_BYTES,
    PING_INTERVAL_MS,
    PING_TIMEOUT_MS,
    RECORD_SEPARATOR,
)


class EngineIOSession:
    """
    In-memory Engine.IO session shared by both transports.

    Notes:
      * Single-process only; replace registry with Redis (or similar) for prod.
      * HTTP long-polling queue contains already-encoded packet segments
        (e.g. "4hello", "2", "bAQIDBA==").

    """

    def __init__(self, sid: str):
        self.sid = sid

        # "polling" or "websocket"
        self.transport: str = "polling"

        # WebSocket consumer currently attached (if any)
        self.websocket: Any | None = None  # EngineIOWebSocketConsumer

        # Application-level EngineIOSocket (see engineio.app)
        self.app_socket: Any | None = None  # EngineIOSocket

        # Outgoing HTTP queue (for polling transport)
        self._queue: asyncio.Queue[str] = asyncio.Queue()

        # Concurrency guard
        self.active_get: bool = False
        self.active_post: bool = False

        # Heartbeat tracking
        now = time.time()
        self.last_seen: float = now
        self.last_ping_sent: float = 0.0
        self.last_pong: float = now

        # Closed flag (logical session closed)
        self.closed: bool = False

    # ------------------------------------------------------------------ #
    # Lifecycle / heartbeat
    # ------------------------------------------------------------------ #

    def touch(self) -> None:
        self.last_seen = time.time()

    def mark_ping_sent(self) -> None:
        self.last_ping_sent = time.time()

    def mark_pong_received(self) -> None:
        self.last_pong = time.time()

    def should_send_ping(self) -> bool:
        if self.closed:
            return False
        now = time.time()
        return (
            self.last_ping_sent == 0.0
            or (now - self.last_ping_sent) * 1000 >= PING_INTERVAL_MS
        )

    def is_timed_out(self) -> bool:
        if self.closed:
            return True
        now = time.time()
        return (now - self.last_pong) * 1000 > 2 * (
            PING_INTERVAL_MS + PING_TIMEOUT_MS
        )

    # ------------------------------------------------------------------ #
    # HTTP long-polling helpers
    # ------------------------------------------------------------------ #

    async def enqueue_http_packet(self, segment: str) -> None:
        """
        Enqueue a pre-encoded packet segment for HTTP polling.

        Examples:
          "2"            (ping)
          "4hello"       (text message)
          "bAQIDBA=="    (binary message, base64 payload)

        """
        if self.closed:
            return
        await self._queue.put(segment)

    async def http_next_payload(self, timeout: float) -> bytes:
        """
        Drain queued segments into a single HTTP payload, separated by
        RECORD_SEPARATOR, bounded by maxPayload.
        """
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return b""

        segments = [first]

        # Non-blocking drain
        while True:
            try:
                segments.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        # Apply maxPayload limit
        payload_parts = []
        total_bytes = 0
        for seg in segments:
            piece = seg if not payload_parts else RECORD_SEPARATOR + seg
            b = piece.encode("utf-8")
            if total_bytes + len(b) > MAX_PAYLOAD_BYTES:
                # Put back segment that didn't fit
                await self._queue.put(seg)
                break
            payload_parts.append(piece)
            total_bytes += len(b)

        if not payload_parts:
            return b""

        return "".join(payload_parts).encode("utf-8")


# ---------------------------------------------------------------------- #
# Global single-process registry
# ---------------------------------------------------------------------- #

_SESSIONS: dict[str, EngineIOSession] = {}
_SESSIONS_LOCK = asyncio.Lock()


async def create_session() -> EngineIOSession:
    async with _SESSIONS_LOCK:
        while True:
            sid = secrets.token_urlsafe(16)
            if sid not in _SESSIONS:
                sess = EngineIOSession(sid)
                _SESSIONS[sid] = sess
                return sess


async def get_session(sid: str) -> EngineIOSession | None:
    return _SESSIONS.get(sid)


async def destroy_session(sid: str) -> None:
    async with _SESSIONS_LOCK:
        _SESSIONS.pop(sid, None)
