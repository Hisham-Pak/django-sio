# socketio/socket.py
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import itertools
import logging
from typing import Any

from ..engineio.app import EngineIOSocket
from . import server as socketio_server  # avoid circular import
from .constants import (
    DEFAULT_NAMESPACE,
    SIO_ACK,
    SIO_BINARY_ACK,
    SIO_BINARY_EVENT,
    SIO_DISCONNECT,
    SIO_EVENT,
)
from .protocol import SocketIOPacket, encode_packet_to_eio

logger = logging.getLogger("sio." + __name__)

AckCallback = Callable[[Any], Awaitable[None]]


@dataclass
class NamespaceSocket:
    """
    Socket.IO "socket" bound to a namespace (e.g. "/", "/chat").
    """

    server: socketio_server.SocketIOServer
    eio: EngineIOSocket
    namespace: str = DEFAULT_NAMESPACE
    id: str = ""  # Socket.IO ID (sid-like)
    state: dict[str, Any] = field(default_factory=dict)
    rooms: set[str] = field(default_factory=set)

    _next_ack_id: itertools.count = field(
        default_factory=lambda: itertools.count(0), init=False
    )
    _pending_acks: dict[int, AckCallback] = field(
        default_factory=dict, init=False
    )

    # ------------------------------------------------------------------ #
    # Low-level send helpers
    # ------------------------------------------------------------------ #

    async def _send_packet(self, pkt: SocketIOPacket) -> None:
        header, attachments = encode_packet_to_eio(pkt)

        logger.debug(
            """
            NamespaceSocket._send_packet socket.id=%s ns=%s type=%s id=%s
            attachments=%d header_len=%d
            """,
            self.id,
            self.namespace,
            pkt.type,
            pkt.id,
            len(attachments),
            len(header),
        )

        # EngineIOSocket._send_text already wraps with EIO "4"
        await self.eio._send_text(header)

        # Then attachments as binary Engine.IO messages "4<bytes>"
        for blob in attachments:
            logger.debug(
                "Sending binary attachment socket.id=%s ns=%s bytes=%d",
                self.id,
                self.namespace,
                len(blob),
            )
            await self.eio._send_binary(blob)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def emit(
        self,
        event: str,
        *args: Any,
        callback: AckCallback | None = None,
    ) -> None:
        data = [event, *args]
        pkt_type = SIO_EVENT

        logger.debug(
            """
            NamespaceSocket.emit socket.id=%s ns=%s event=%s args_count=%d
            has_ack=%s
            """,
            self.id,
            self.namespace,
            event,
            len(args),
            callback is not None,
        )

        pkt = SocketIOPacket(
            type=pkt_type,
            namespace=self.namespace,
            data=data,
        )

        if callback is not None:
            ack_id = next(self._next_ack_id)
            self._pending_acks[ack_id] = callback
            pkt.id = ack_id
            logger.debug(
                "Registered ack callback socket.id=%s ns=%s ack_id=%d",
                self.id,
                self.namespace,
                ack_id,
            )

        await self._send_packet(pkt)

    async def send(self, *args: Any) -> None:
        logger.debug(
            "NamespaceSocket.send socket.id=%s ns=%s args_count=%d",
            self.id,
            self.namespace,
            len(args),
        )
        await self.emit("message", *args)

    async def disconnect(self) -> None:
        logger.info(
            "NamespaceSocket.disconnect requested socket.id=%s ns=%s",
            self.id,
            self.namespace,
        )
        pkt = SocketIOPacket(
            type=SIO_DISCONNECT,
            namespace=self.namespace,
        )
        await self._send_packet(pkt)
        await self.server._on_client_disconnect(self, "client_disconnect")

    # ------------------------------------------------------------------ #
    # Rooms API
    # ------------------------------------------------------------------ #

    async def join(self, room: str) -> None:
        """
        Join a logical room. Internally:

        * track in self.rooms
        * add underlying WebSocket channel to a Channels group

        """
        if room in self.rooms:
            logger.debug(
                """
                NamespaceSocket.join no-op (already in room) socket.id=%s ns=%s
                room=%s
                """,
                self.id,
                self.namespace,
                room,
            )
            return
        self.rooms.add(room)
        logger.info(
            "NamespaceSocket.join socket.id=%s ns=%s room=%s",
            self.id,
            self.namespace,
            room,
        )

        session = self.eio._session  # internal; we control both sides
        ws = session.websocket
        if ws is not None and ws.channel_layer is not None:
            group = self.server._group_name(self.namespace, room)
            logger.debug(
                """
                Adding WebSocket to channel layer group socket.id=%s group=%s
                """,
                self.id,
                group,
            )
            await ws.channel_layer.group_add(group, ws.channel_name)

    async def leave(self, room: str) -> None:
        if room not in self.rooms:
            logger.debug(
                """
                NamespaceSocket.leave no-op (not in room) socket.id=%s ns=%s
                room=%s
                """,
                self.id,
                self.namespace,
                room,
            )
            return
        self.rooms.remove(room)
        logger.info(
            "NamespaceSocket.leave socket.id=%s ns=%s room=%s",
            self.id,
            self.namespace,
            room,
        )

        session = self.eio._session
        ws = session.websocket
        if ws is not None and ws.channel_layer is not None:
            group = self.server._group_name(self.namespace, room)
            logger.debug(
                """
                Removing WebSocket from channel layer group socket.id=%s
                group=%s
                """,
                self.id,
                group,
            )
            await ws.channel_layer.group_discard(group, ws.channel_name)

    async def leave_all(self) -> None:
        """
        Leave all rooms this socket is in.
        """
        logger.debug(
            "NamespaceSocket.leave_all socket.id=%s ns=%s rooms=%s",
            self.id,
            self.namespace,
            list(self.rooms),
        )
        for room in list(self.rooms):
            await self.leave(room)

    # ------------------------------------------------------------------ #
    # Incoming packets from client
    # ------------------------------------------------------------------ #

    async def _handle_packet_from_client(self, pkt: SocketIOPacket) -> None:
        logger.debug(
            """
            NamespaceSocket._handle_packet_from_client socket.id=%s ns=%s
            type=%s id=%s
            """,
            self.id,
            self.namespace,
            pkt.type,
            pkt.id,
        )
        if pkt.type in (SIO_EVENT, SIO_BINARY_EVENT):
            await self._handle_event(pkt)
        elif pkt.type in (SIO_ACK, SIO_BINARY_ACK):
            await self._handle_ack(pkt)
        elif pkt.type == SIO_DISCONNECT:
            logger.info(
                "Client initiated disconnect socket.id=%s ns=%s",
                self.id,
                self.namespace,
            )
            await self.server._on_client_disconnect(self, "client_disconnect")

    async def _handle_event(self, pkt: SocketIOPacket) -> None:
        data = pkt.data or []
        logger.debug(
            "NamespaceSocket._handle_event socket.id=%s ns=%s data_type=%s",
            self.id,
            self.namespace,
            type(data).__name__,
        )
        if not isinstance(data, list) or not data:
            logger.warning(
                """
                Bad event payload, forcing disconnect socket.id=%s ns=%s
                data=%r
                """,
                self.id,
                self.namespace,
                data,
            )
            await self.server._force_disconnect_bad_packet(
                self, "bad_event_payload"
            )
            return

        event = data[0]
        args = data[1:]

        ack_cb: AckCallback | None = None
        if pkt.id is not None:
            ack_id = pkt.id

            async def _ack_fn(*ack_args: Any) -> None:
                logger.debug(
                    "Sending ack for socket.id=%s ns=%s ack_id=%d",
                    self.id,
                    self.namespace,
                    ack_id,
                )
                ack_pkt = SocketIOPacket(
                    type=SIO_ACK,
                    namespace=self.namespace,
                    data=list(ack_args),
                    id=ack_id,
                )
                await self._send_packet(ack_pkt)

            ack_cb = _ack_fn

        await self.server._dispatch_event(self, event, args, ack_cb)

    async def _handle_ack(self, pkt: SocketIOPacket) -> None:
        if pkt.id is None:
            logger.debug(
                "Ack packet without id ignored socket.id=%s ns=%s",
                self.id,
                self.namespace,
            )
            return
        cb = self._pending_acks.pop(pkt.id, None)
        if cb is None:
            logger.debug(
                "No pending ack callback for id=%d socket.id=%s ns=%s",
                pkt.id,
                self.id,
                self.namespace,
            )
            return

        args = pkt.data or []
        if not isinstance(args, list):
            args = [args]

        logger.debug(
            "Executing ack callback id=%d socket.id=%s ns=%s args_count=%d",
            pkt.id,
            self.id,
            self.namespace,
            len(args),
        )
        await cb(*args)
