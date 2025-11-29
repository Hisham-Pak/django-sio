from __future__ import annotations

import asyncio
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

        if eio != ENGINE_IO_VERSION or transport != TRANSPORT_WEBSOCKET:
            await self.close()
            return

        if sid:
            # Upgrade from existing polling session
            session = await get_session(sid)
            if not session or session.is_timed_out() or session.closed:
                await self.close()
                return

            # Only one WebSocket per session.
            if session.websocket is not None and session.websocket is not self:
                await self.close()
                return

            self.session = session
            session.websocket = self
            await self.accept()
        else:
            # WebSocket-only session: create and send open packet over WS.
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

            # Notify app for WS-only sessions
            app = get_engineio_app()
            socket = get_or_create_socket(session)
            await app.on_connect(socket)

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self, code):
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self.session is not None:
            # Notify app + drop session
            await close_session(self.session, reason="websocket_disconnect")
            self.session.websocket = None
            self.session = None

    # ------------------------------------------------------------------ #
    # Heartbeat (server ping -> client pong)
    # ------------------------------------------------------------------ #

    async def _heartbeat_loop(self):
        try:
            while self.session and not self.session.closed:
                await asyncio.sleep(PING_INTERVAL_MS / 1000.0)

                if not self.session or self.session.closed:
                    break

                # Send ping
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
                    await self.close()
                    break
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------ #
    # Sending helpers
    # ------------------------------------------------------------------ #

    async def _send_text_packet(self, packet_type: str, data: str = ""):
        frame = encode_ws_text_frame(packet_type, data)
        await self.send(text_data=frame)

    async def _send_binary_packet(self, packet_type: str, data: bytes):
        frame = encode_ws_binary_frame(packet_type, data)
        await self.send(bytes_data=frame)

    # ------------------------------------------------------------------ #
    # Receiving frames
    # ------------------------------------------------------------------ #

    async def receive(self, text_data=None, bytes_data=None):
        if not self.session or self.session.closed:
            await self.close()
            return

        self.session.touch()
        try:
            if text_data is not None:
                pkt = decode_ws_text_frame(text_data)
            else:
                pkt = decode_ws_binary_frame(bytes_data)
        except ValueError:
            await self.close()
            return

        app = get_engineio_app()
        socket = get_or_create_socket(self.session)

        # Handle packet types
        if pkt.type == "2":  # ping (including 'probe' during upgrade)
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
            self.session.mark_pong_received()

        elif pkt.type == "5":  # upgrade complete
            # Switch primary transport to WebSocket
            self.session.transport = "websocket"


            # Flush any pending HTTP long-polling queue segments to the
            # WebSocket, so messages enqueued before upgrade (e.g. initial
            # "live_state") are not silently lost when the client stops polling
            if self.session.websocket is self:
                # session._queue contains pre-encoded Engine.IO packet
                # segments,
                # e.g. "4<socket.io header>", "2", "b<base64>", etc.
                while True:
                    try:
                        segment = self.session._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    # For WebSocket, each Engine.IO packet is a separate frame
                    # "<type>[<data>]". Our segments are already exactly that,
                    # so just send each as its own text frame.
                    await self.send(text_data=segment)

            # Send noop to any pending HTTP GET to close polling cleanly.
            await self.session.enqueue_http_packet("6")

        elif pkt.type == "4":  # message
            await app.on_message(socket, pkt.data, pkt.binary)

        elif pkt.type == "1":  # close
            await close_session(self.session, reason="client_close")
            await self.close()

        # "noop" (6) and others are ignored here

    # ------------------------------------------------------------------ #
    # Channel layer -> WebSocket broadcasting (sio.broadcast)
    # ------------------------------------------------------------------ #

    async def sio_broadcast(self, event):
        """
        Called by channel layer when SocketIOServer does group_send(...,
        type="sio.broadcast").

        It receives the already-encoded Socket.IO header and the list of binary
        attachments, and replays them to the actual WebSocket client as
        Engine.IO "message" packets.

        """
        if not self.session or self.session.closed:
            return

        header: str = event["header"]
        attachments: list[bytes] = event.get("attachments", [])

        # Text frame: Engine.IO message type 4 + Socket.IO header
        await self.send(text_data="4" + header)

        # Binary attachments as Engine.IO message (type 4 + raw bytes)
        for blob in attachments:
            await self.send(bytes_data=b"4" + blob)
