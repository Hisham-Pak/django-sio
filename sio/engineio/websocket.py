# engineio/websocket.py
from __future__ import annotations

import asyncio
import logging
import time

from channels.generic.websocket import AsyncWebsocketConsumer

from .app import (
    close_session,
    get_engineio_app,
    get_or_create_socket,
)
from .constants import (
    ENGINE_IO_VERSION,
    PING_INTERVAL_MS,
    PING_TIMEOUT_MS,
    TRANSPORT_WEBSOCKET,
)
from .packets import (
    decode_ws_binary_frame,
    decode_ws_text_frame,
    encode_open_packet,
    encode_ws_binary_frame,
    encode_ws_text_frame,
)
from .session import (
    EngineIOSession,
    create_session,
    get_session,
)
from .utils import parse_query

logger = logging.getLogger("sio." + __name__)


class EngineIOWebSocketConsumer(AsyncWebsocketConsumer):
    """
    Engine.IO v4 WebSocket transport.

    Handles:
      * WebSocket-only sessions
      * Upgrade from HTTP polling (probe + upgrade)
      * Heartbeat (server ping, client pong)
      * Application callbacks (via engineio.app)

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session: EngineIOSession | None = None
        self._heartbeat_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self):
        qs = parse_query(self.scope)
        eio = qs.get("EIO")
        transport = qs.get("transport")
        sid = qs.get("sid")

        logger.debug(
            "EngineIOWebSocketConsumer.connect path=%s qs=%s",
            self.scope.get("path"),
            qs,
        )

        if eio != ENGINE_IO_VERSION or transport != TRANSPORT_WEBSOCKET:
            logger.warning(
                "Invalid WS Engine.IO params eio=%s transport=%s expected_eio=%s",
                eio,
                transport,
                ENGINE_IO_VERSION,
            )
            await self.close()
            return

        if sid:
            # Upgrade from existing polling session
            logger.debug("WebSocket upgrade requested sid=%s", sid)
            session = await get_session(sid)
            if not session or session.is_timed_out() or session.closed:
                logger.warning(
                    "WebSocket upgrade failed, unknown/timed-out/closed sid=%s",
                    sid,
                )
                await self.close()
                return

            # Only one WebSocket per session.
            if session.websocket is not None and session.websocket is not self:
                logger.warning(
                    "WebSocket upgrade denied, existing websocket for sid=%s",
                    session.sid,
                )
                # Accept the WebSocket and then immediately close it so that
                # the client observes a normal WebSocket close (no HTTP 403),
                # which matches the Engine.IO test suite expectation that a
                # second WS with the same sid is simply "ignored".
                await self.accept()
                await self.close()
                return

            self.session = session
            session.websocket = self
            await self.accept()
            logger.info(
                "WebSocket upgraded for existing Engine.IO session sid=%s",
                session.sid,
            )
        else:
            # WebSocket-only session: create and send open packet over WS.
            logger.debug("Creating WebSocket-only Engine.IO session")
            session = await create_session()
            session.transport = "websocket"
            session.websocket = self
            self.session = session

            await self.accept()

            open_packet = encode_open_packet(
                sid=session.sid,
                upgrades=[],
            )
            await self.send(text_data=open_packet)

            logger.info(
                "WebSocket-only Engine.IO session created sid=%s",
                session.sid,
            )

            # Notify app for WS-only sessions
            app = get_engineio_app()
            socket = get_or_create_socket(session)
            logger.debug("Notifying app.on_connect sid=%s (websocket)", session.sid)
            await app.on_connect(socket)

        # Start heartbeat task
        logger.debug("Starting WS heartbeat loop sid=%s", self.session.sid)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self, code):
        logger.info(
            "EngineIOWebSocketConsumer.disconnect code=%s sid=%s",
            code,
            self.session.sid if self.session else None,
        )
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self.session is not None:
            # Notify app + drop session
            sid = self.session.sid
            await close_session(self.session, reason="websocket_disconnect")
            self.session.websocket = None
            self.session = None
            logger.debug("WebSocket session reference cleared sid=%s", sid)

    # ------------------------------------------------------------------ #
    # Heartbeat (server ping -> client pong)
    # ------------------------------------------------------------------ #

    async def _heartbeat_loop(self):
        logger.debug(
            "Heartbeat loop started sid=%s",
            self.session.sid if self.session else None,
        )
        try:
            while self.session and not self.session.closed:
                await asyncio.sleep(PING_INTERVAL_MS / 1000.0)

                if not self.session or self.session.closed:
                    logger.debug(
                        "Heartbeat loop exiting (no session/closed) sid=%s",
                        self.session.sid if self.session else None,
                    )
                    break

                # Send ping
                logger.debug("Heartbeat ping sid=%s", self.session.sid)
                await self._send_text_packet("2")
                self.session.mark_ping_sent()
                sent_at = time.time()

                # Wait pingTimeout for pong
                await asyncio.sleep(PING_TIMEOUT_MS / 1000.0)
                if (
                    not self.session
                    or self.session.closed
                    or self.session.last_pong < sent_at
                ):
                    logger.warning(
                        "Heartbeat timeout, closing WebSocket sid=%s last_pong=%f sent_at=%f",
                        self.session.sid if self.session else None,
                        self.session.last_pong if self.session else -1,
                        sent_at,
                    )
                    await self.close()
                    break
        except asyncio.CancelledError:
            logger.debug("Heartbeat loop cancelled")
        finally:
            logger.debug("Heartbeat loop finished")

    # ------------------------------------------------------------------ #
    # Sending helpers
    # ------------------------------------------------------------------ #

    async def _send_text_packet(self, packet_type: str, data: str = ""):
        frame = encode_ws_text_frame(packet_type, data)
        logger.debug(
            "Sending WS text packet type=%s len=%d sid=%s",
            packet_type,
            len(frame),
            self.session.sid if self.session else None,
        )
        await self.send(text_data=frame)

    async def _send_binary_packet(self, packet_type: str, data: bytes):
        frame = encode_ws_binary_frame(packet_type, data)
        logger.debug(
            "Sending WS binary packet type=%s len=%d sid=%s",
            packet_type,
            len(frame),
            self.session.sid if self.session else None,
        )
        await self.send(bytes_data=frame)

    # ------------------------------------------------------------------ #
    # Receiving frames
    # ------------------------------------------------------------------ #

    async def receive(self, text_data=None, bytes_data=None):
        if not self.session or self.session.closed:
            logger.warning(
                "WS receive for missing/closed session, closing websocket"
            )
            await self.close()
            return

        self.session.touch()
        try:
            if text_data is not None:
                logger.debug(
                    "WS text frame received sid=%s len=%d",
                    self.session.sid,
                    len(text_data),
                )
                pkt = decode_ws_text_frame(text_data)
            else:
                logger.debug(
                    "WS binary frame received sid=%s len=%d",
                    self.session.sid,
                    len(bytes_data or b""),
                )
                pkt = decode_ws_binary_frame(bytes_data or b"")
        except ValueError as e:
            logger.warning(
                "Invalid WS frame for sid=%s error=%s", self.session.sid, e
            )
            await self.close()
            return

        app = get_engineio_app()
        socket = get_or_create_socket(self.session)

        # Handle packet types
        if pkt.type == "2":  # ping (including 'probe' during upgrade)
            logger.debug(
                "WS ping received sid=%s probe=%s",
                self.session.sid,
                (not pkt.binary and pkt.data == "probe"),
            )
            if not pkt.binary and pkt.data == "probe":
                # Upgrade probe: respond with pong "probe".
                await self._send_text_packet("3", "probe")
            else:
                # Regular ping from client (rare)
                if pkt.binary:
                    await self._send_binary_packet("3", pkt.data or b"")
                else:
                    await self._send_text_packet("3", str(pkt.data or ""))

        elif pkt.type == "3":  # pong
            logger.debug("WS pong received sid=%s", self.session.sid)
            self.session.mark_pong_received()

        elif pkt.type == "5":  # upgrade complete
            logger.info(
                "Engine.IO transport upgraded to WebSocket sid=%s",
                self.session.sid,
            )
            # Switch primary transport to WebSocket
            self.session.transport = "websocket"

            # Flush any pending HTTP long-polling queue segments to the WebSocket
            if self.session.websocket is self:
                logger.debug(
                    "Flushing HTTP queue to WebSocket sid=%s", self.session.sid
                )
                while True:
                    try:
                        segment = self.session._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    await self.send(text_data=segment)

            # Send noop to any pending HTTP GET to close polling cleanly.
            await self.session.enqueue_http_packet("6")

        elif pkt.type == "4":  # message
            logger.debug(
                "Engine.IO WS message received sid=%s binary=%s len=%s",
                self.session.sid,
                pkt.binary,
                len(pkt.data) if pkt.data is not None else 0,
            )
            await app.on_message(socket, pkt.data, pkt.binary)

        elif pkt.type == "1":  # close
            logger.info("Engine.IO WS close packet received sid=%s", self.session.sid)
            await close_session(self.session, reason="client_close")
            await self.close()

        else:
            logger.debug(
                "Ignoring WS packet type=%s sid=%s", pkt.type, self.session.sid
            )

    # ------------------------------------------------------------------ #
    # Channel layer -> WebSocket broadcasting (sio.broadcast)
    # ------------------------------------------------------------------ #

    async def sio_broadcast(self, event):
        """
        Called by channel layer when SocketIOServer does group_send(...,
        type="sio.broadcast").
        """
        if not self.session or self.session.closed:
            logger.debug(
                "sio_broadcast ignored for missing/closed session"
            )
            return

        header: str = event["header"]
        attachments: list[bytes] = event.get("attachments", [])

        logger.debug(
            "sio_broadcast sid=%s header_len=%d attachments=%d",
            self.session.sid,
            len(header),
            len(attachments),
        )

        # Text frame: Engine.IO message type 4 + Socket.IO header
        await self.send(text_data="4" + header)

        # Binary attachments as Engine.IO message (type 4 + raw bytes)
        for blob in attachments:
            await self.send(bytes_data=b"4" + blob)
