# engineio/polling.py
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from channels.generic.http import AsyncHttpConsumer

from .app import (
    close_session,
    get_engineio_app,
    get_or_create_socket,
)
from .constants import (
    ENGINE_IO_VERSION,
    PING_INTERVAL_MS,
    PING_TIMEOUT_MS,
    TRANSPORT_POLLING,
)
from .packets import (
    Packet,
    decode_http_payload,
    encode_open_packet,
    encode_text_packet,
)
from .session import (
    EngineIOSession,
    create_session,
    get_session,
)
from .utils import parse_query

logger = logging.getLogger("sio." + __name__)

LONG_POLL_TIMEOUT_S = (PING_INTERVAL_MS + PING_TIMEOUT_MS) / 1000.0


class LongPollingConsumer(AsyncHttpConsumer):
    """
    Engine.IO v4 HTTP long-polling transport.

    * Uses base64 for binary payloads, prefixed with 'b' (HTTP only).
    * Exposes application-level events via engineio.app.
    * Implements Engine.IO heartbeat (ping/pong) over HTTP.

    """

    async def handle(self, body: bytes):
        method = self.scope["method"].upper()
        qs = parse_query(self.scope)

        logger.debug(
            "LongPollingConsumer.handle method=%s path=%s qs=%s body_len=%d",
            method,
            self.scope.get("path"),
            qs,
            len(body) if body is not None else 0,
        )

        eio = qs.get("EIO")
        transport = qs.get("transport")
        sid = qs.get("sid")

        # Validate basic query params
        if eio != ENGINE_IO_VERSION or transport != TRANSPORT_POLLING:
            logger.warning(
                "Invalid Engine.IO query parameters eio=%s transport=%s expected_eio=%s",
                eio,
                transport,
                ENGINE_IO_VERSION,
            )
            await self.send_response(
                400,
                b"Invalid Engine.IO query parameters",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        # Handshake: GET with no sid
        if method == "GET" and not sid:
            logger.info("Handling Engine.IO HTTP handshake")
            await self._handle_handshake()
            return

        # From here on, sid is mandatory
        if not sid:
            logger.warning("Missing sid on non-handshake request")
            await self.send_response(
                400,
                b"Missing sid",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        session = await get_session(sid)
        if not session:
            logger.warning("Unknown or expired sid=%s", sid)
            await self.send_response(
                400,
                b"Unknown or expired sid",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        if session.is_timed_out():
            logger.info("Session timed out sid=%s", sid)
            await close_session(session, reason="timeout")
            await self.send_response(
                400,
                b"Unknown or expired sid",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        if session.closed:
            logger.info("Request for logically closed session sid=%s", sid)
            await self.send_response(
                400,
                b"Unknown or expired sid",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        # Session exists and is alive
        if session.transport == "websocket":
            logger.warning(
                "Polling transport closed after WebSocket upgrade sid=%s",
                sid,
            )
            await self.send_response(
                400,
                b"Polling transport closed (upgraded to WebSocket)",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        session.touch()

        if method == "GET":
            await self._handle_get(session)
        elif method == "POST":
            await self._handle_post(session, body)
        else:
            logger.warning(
                "Method not allowed on Engine.IO polling sid=%s method=%s",
                sid,
                method,
            )
            await self.send_response(
                405,
                b"Method not allowed",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )

    # ------------------------------------------------------------------ #
    # Handshake
    # ------------------------------------------------------------------ #

    async def _handle_handshake(self):
        session = await create_session()

        logger.debug(
            "Created Engine.IO session sid=%s (HTTP polling handshake)",
            session.sid,
        )

        # Advertise websocket upgrade
        open_packet = encode_open_packet(
            sid=session.sid,
            upgrades=["websocket"],
        )
        session.touch()

        await self.send_response(
            200,
            open_packet.encode("utf-8"),
            headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
        )

        # Now that handshake is done, notify app.
        app = get_engineio_app()
        socket = get_or_create_socket(session)
        logger.debug("Notifying app.on_connect sid=%s (polling)", session.sid)
        await app.on_connect(socket)

    # ------------------------------------------------------------------ #
    # GET = receive packets
    # ------------------------------------------------------------------ #

    async def _handle_get(self, session: EngineIOSession):
        logger.debug(
            "LongPollingConsumer._handle_get sid=%s active_get=%s",
            session.sid,
            session.active_get,
        )
        if session.active_get:
            logger.warning("Concurrent GET detected sid=%s", session.sid)
            await close_session(session, reason="concurrent_get")
            await self.send_response(
                400,
                b"Multiple concurrent GET not allowed",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        session.active_get = True
        ping_task = None
        try:
            # Immediate ping if the interval has already elapsed (or first ping)
            if session.should_send_ping():
                logger.debug("Immediate ping for sid=%s", session.sid)
                await session.enqueue_http_packet(encode_text_packet("2"))
                session.mark_ping_sent()
            else:
                # Schedule a ping during this long poll when the interval elapses
                # since the last ping was sent.
                now = time.time()
                last_ping = getattr(session, "last_ping_sent", now)
                elapsed_ms = int((now - last_ping) * 1000)
                remaining_ms = max(0, PING_INTERVAL_MS - elapsed_ms)
                logger.debug(
                    "Scheduling delayed ping sid=%s remaining_ms=%d",
                    session.sid,
                    remaining_ms,
                )

                async def delayed_ping():
                    await asyncio.sleep(remaining_ms / 1000.0)
                    if session.closed or not session.active_get:
                        logger.debug(
                            "Skipping delayed ping sid=%s closed=%s active_get=%s",
                            session.sid,
                            session.closed,
                            session.active_get,
                        )
                        return
                    logger.debug("Delayed ping executing sid=%s", session.sid)
                    await session.enqueue_http_packet(encode_text_packet("2"))
                    session.mark_ping_sent()

                ping_task = asyncio.create_task(delayed_ping())

            body = await session.http_next_payload(timeout=LONG_POLL_TIMEOUT_S)

            logger.debug(
                "HTTP payload ready sid=%s len=%d", session.sid, len(body)
            )

            await self.send_response(
                200,
                body,
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
        finally:
            session.active_get = False
            if ping_task is not None:
                ping_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ping_task
            logger.debug(
                "LongPollingConsumer._handle_get finished sid=%s", session.sid
            )

    # ------------------------------------------------------------------ #
    # POST = send packets
    # ------------------------------------------------------------------ #

    async def _handle_post(self, session: EngineIOSession, body: bytes):
        logger.debug(
            "LongPollingConsumer._handle_post sid=%s body_len=%d active_post=%s",
            session.sid,
            len(body),
            session.active_post,
        )
        if session.active_post:
            logger.warning("Concurrent POST detected sid=%s", session.sid)
            await close_session(session, reason="concurrent_post")
            await self.send_response(
                400,
                b"Multiple concurrent POST not allowed",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
            return

        session.active_post = True
        try:
            try:
                packets = decode_http_payload(body)
                logger.debug(
                    "Decoded HTTP POST payload sid=%s packets=%d",
                    session.sid,
                    len(packets),
                )
            except ValueError as e:
                logger.warning(
                    "Bad HTTP payload sid=%s error=%s", session.sid, e
                )
                await self.send_response(
                    400,
                    f"Bad payload: {e}".encode(),
                    headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
                )
                return

            app = get_engineio_app()
            socket = get_or_create_socket(session)

            for pkt in packets:
                await self._handle_packet_from_http(session, socket, app, pkt)

            # Spec: POST success => 200 "ok".
            await self.send_response(
                200,
                b"ok",
                headers=[(b"Content-Type", b"text/plain; charset=utf-8")],
            )
        finally:
            session.active_post = False
            logger.debug(
                "LongPollingConsumer._handle_post finished sid=%s", session.sid
            )

    async def _handle_packet_from_http(
        self,
        session: EngineIOSession,
        socket,
        app,
        pkt: Packet,
    ):
        logger.debug(
            "_handle_packet_from_http sid=%s type=%s binary=%s",
            session.sid,
            pkt.type,
            pkt.binary,
        )
        # pong
        if pkt.type == "3":
            logger.debug("HTTP pong received sid=%s", session.sid)
            session.mark_pong_received()

        # message (text or binary)
        elif pkt.type == "4":
            logger.debug(
                "HTTP message received sid=%s binary=%s len=%s",
                session.sid,
                pkt.binary,
                len(pkt.data) if pkt.data is not None else 0,
            )
            await app.on_message(socket, pkt.data, pkt.binary)

        # close
        elif pkt.type == "1":
            logger.info("HTTP close received sid=%s", session.sid)
            await close_session(session, reason="client_close")

        # ping (rare from client)
        elif pkt.type == "2":
            logger.debug("HTTP ping received sid=%s", session.sid)
            await session.enqueue_http_packet(
                encode_text_packet("3", str(pkt.data or ""))
            )

        # upgrade / noop: ignored here
        else:
            logger.debug(
                "Ignoring HTTP packet type=%s sid=%s", pkt.type, session.sid
            )

    async def disconnect(self):
        # Requests are one-shot; nothing to clean per-request.
        logger.debug("LongPollingConsumer.disconnect called")
        pass
