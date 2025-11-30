# engineio/session.py
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any
import logging

from .constants import (
    MAX_PAYLOAD_BYTES,
    PING_INTERVAL_MS,
    PING_TIMEOUT_MS,
    RECORD_SEPARATOR,
)

logger = logging.getLogger("sio." + __name__)


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

        logger.debug("EngineIOSession created sid=%s", sid)

    # ------------------------------------------------------------------ #
    # Lifecycle / heartbeat
    # ------------------------------------------------------------------ #

    def touch(self) -> None:
        self.last_seen = time.time()
        logger.debug("Session touched sid=%s last_seen=%f", self.sid, self.last_seen)

    def mark_ping_sent(self) -> None:
        self.last_ping_sent = time.time()
        logger.debug("Ping sent sid=%s ts=%f", self.sid, self.last_ping_sent)

    def mark_pong_received(self) -> None:
        self.last_pong = time.time()
        logger.debug("Pong received sid=%s ts=%f", self.sid, self.last_pong)

    def should_send_ping(self) -> bool:
        if self.closed:
            logger.debug("should_send_ping -> False (closed) sid=%s", self.sid)
            return False
        now = time.time()
        result = (
            self.last_ping_sent == 0.0
            or (now - self.last_ping_sent) * 1000 >= PING_INTERVAL_MS
        )
        logger.debug(
            "should_send_ping sid=%s result=%s last_ping_sent=%f now=%f",
            self.sid,
            result,
            self.last_ping_sent,
            now,
        )
        return result

    def is_timed_out(self) -> bool:
        if self.closed:
            logger.debug("is_timed_out -> True (closed) sid=%s", self.sid)
            return True
        now = time.time()
        timed_out = (now - self.last_pong) * 1000 > 2 * (
            PING_INTERVAL_MS + PING_TIMEOUT_MS
        )
        logger.debug(
            "is_timed_out sid=%s timed_out=%s last_pong=%f now=%f",
            self.sid,
            timed_out,
            self.last_pong,
            now,
        )
        return timed_out

    # ------------------------------------------------------------------ #
    # HTTP long-polling helpers
    # ------------------------------------------------------------------ #

    async def enqueue_http_packet(self, segment: str) -> None:
        """
        Enqueue a pre-encoded packet segment for HTTP polling.
        """
        if self.closed:
            logger.debug(
                "Skipping enqueue on closed session sid=%s segment_preview=%r",
                self.sid,
                segment[:50],
            )
            return
        logger.debug(
            "Enqueue HTTP packet sid=%s segment_len=%d",
            self.sid,
            len(segment),
        )
        await self._queue.put(segment)

    async def http_next_payload(self, timeout: float) -> bytes:
        """
        Drain queued segments into a single HTTP payload, separated by
        RECORD_SEPARATOR, bounded by maxPayload.
        """
        logger.debug(
            "http_next_payload waiting sid=%s timeout=%s", self.sid, timeout
        )
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            logger.debug("http_next_payload timeout sid=%s", self.sid)
            return b""

        segments = [first]

        # Non-blocking drain
        while True:
            try:
                segments.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        logger.debug(
            "http_next_payload draining sid=%s segments=%d",
            self.sid,
            len(segments),
        )

        # Apply maxPayload limit
        payload_parts = []
        total_bytes = 0
        for seg in segments:
            piece = seg if not payload_parts else RECORD_SEPARATOR + seg
            b = piece.encode("utf-8")
            if total_bytes + len(b) > MAX_PAYLOAD_BYTES:
                logger.debug(
                    "http_next_payload reached MAX_PAYLOAD_BYTES sid=%s total_bytes=%d",
                    self.sid,
                    total_bytes,
                )
                # Put back segment that didn't fit
                await self._queue.put(seg)
                break
            payload_parts.append(piece)
            total_bytes += len(b)

        if not payload_parts:
            logger.debug(
                "http_next_payload produced empty payload sid=%s", self.sid
            )
            return b""

        result = "".join(payload_parts).encode("utf-8")
        logger.debug(
            "http_next_payload built sid=%s payload_len=%d parts=%d",
            self.sid,
            len(result),
            len(payload_parts),
        )
        return result


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
                logger.debug("Session registered sid=%s", sid)
                return sess


async def get_session(sid: str) -> EngineIOSession | None:
    sess = _SESSIONS.get(sid)
    logger.debug("get_session sid=%s found=%s", sid, sess is not None)
    return sess


async def destroy_session(sid: str) -> None:
    async with _SESSIONS_LOCK:
        removed = _SESSIONS.pop(sid, None)
        logger.debug(
            "destroy_session sid=%s removed=%s", sid, removed is not None
        )
