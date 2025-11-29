from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import itertools
from typing import TYPE_CHECKING, Any

from ..engineio.app import EngineIOSocket
from .constants import (
    DEFAULT_NAMESPACE,
    SIO_ACK,
    SIO_BINARY_ACK,
    SIO_BINARY_EVENT,
    SIO_DISCONNECT,
    SIO_EVENT,
)
from .protocol import SocketIOPacket, encode_packet_to_eio

if TYPE_CHECKING:
    # Avoid circular import
    from .server import SocketIOServer

AckCallback = Callable[[Any], Awaitable[None]]


@dataclass
class NamespaceSocket:
    """
    Socket.IO "socket" bound to a namespace (e.g. "/", "/chat").
    """

    server: SocketIOServer
    eio: EngineIOSocket
    namespace: str = DEFAULT_NAMESPACE
    id: str = ""  # Socket.IO ID (sid-like)
    state: dict[str, Any] = field(default_factory=dict)
    rooms: set[str] = field(default_factory=set)  # NEW

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

        # EngineIOSocket._send_text already wraps with EIO "4"
        await self.eio._send_text(header)

        # Then attachments as binary Engine.IO messages "4<bytes>"
        for blob in attachments:
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

        pkt = SocketIOPacket(
            type=pkt_type,
            namespace=self.namespace,
            data=data,
        )

        if callback is not None:
            ack_id = next(self._next_ack_id)
            self._pending_acks[ack_id] = callback
            pkt.id = ack_id

        await self._send_packet(pkt)

    async def send(self, *args: Any) -> None:
        await self.emit("message", *args)

    async def disconnect(self) -> None:
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
            return
        self.rooms.add(room)

        session = self.eio._session  # internal; we control both sides
        ws = session.websocket
        if ws is not None and ws.channel_layer is not None:
            group = self.server._group_name(self.namespace, room)
            await ws.channel_layer.group_add(group, ws.channel_name)

    async def leave(self, room: str) -> None:
        if room not in self.rooms:
            return
        self.rooms.remove(room)

        session = self.eio._session
        ws = session.websocket
        if ws is not None and ws.channel_layer is not None:
            group = self.server._group_name(self.namespace, room)
            await ws.channel_layer.group_discard(group, ws.channel_name)

    async def leave_all(self) -> None:
        """
        Leave all rooms this socket is in.
        """
        for room in list(self.rooms):
            await self.leave(room)

    # ------------------------------------------------------------------ #
    # Incoming packets from client
    # ------------------------------------------------------------------ #

    async def _handle_packet_from_client(self, pkt: SocketIOPacket) -> None:
        if pkt.type in (SIO_EVENT, SIO_BINARY_EVENT):
            await self._handle_event(pkt)
        elif pkt.type in (SIO_ACK, SIO_BINARY_ACK):
            await self._handle_ack(pkt)
        elif pkt.type == SIO_DISCONNECT:
            await self.server._on_client_disconnect(self, "client_disconnect")

    async def _handle_event(self, pkt: SocketIOPacket) -> None:
        data = pkt.data or []
        if not isinstance(data, list) or not data:
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
            return
        cb = self._pending_acks.pop(pkt.id, None)
        if cb is None:
            return

        args = pkt.data or []
        if not isinstance(args, list):
            args = [args]

        await cb(*args)
