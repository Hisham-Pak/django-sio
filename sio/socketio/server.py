from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import itertools
import re
from typing import Any

from channels.layers import get_channel_layer

from ..engineio.app import (
    EngineIOApplication,
    EngineIOSocket,
    set_engineio_app,
)
from .constants import (
    DEFAULT_NAMESPACE,
    SIO_CONNECT,
    SIO_CONNECT_ERROR,
    SIO_EVENT,
)
from .protocol import SocketIOPacket, SocketIOParser, encode_packet_to_eio
from .socket import NamespaceSocket

EventHandler = Callable[
    [NamespaceSocket, list[Any], Callable[..., Awaitable[None]] | None],
    Awaitable[None],
]
ConnectHandler = Callable[[NamespaceSocket, Any], Awaitable[bool]]
DisconnectHook = Callable[[NamespaceSocket, str], Awaitable[None]]

GROUP_ALLOWED_RE = re.compile(r"[^0-9A-Za-z_\-\.]")


@dataclass
class Namespace:
    name: str
    server: SocketIOServer
    listeners: dict[str, EventHandler] = field(default_factory=dict)
    connect_handler: ConnectHandler | None = None

    def on(self, event: str) -> Callable[[EventHandler], EventHandler]:
        def decorator(fn: EventHandler) -> EventHandler:
            self.listeners[event] = fn
            return fn

        return decorator

    def on_connect(self, fn: ConnectHandler) -> ConnectHandler:
        self.connect_handler = fn
        return fn


class SocketIOServer(EngineIOApplication):
    """
    Socket.IO server on top of Engine.IO, with rooms & broadcasting via
    Channel's channel layer.
    """

    def __init__(self):
        super().__init__()
        self._namespaces: dict[str, Namespace] = {}
        self._parsers: dict[str, SocketIOParser] = {}
        self._sockets: dict[tuple[str, str], NamespaceSocket] = {}
        self._next_socket_id = itertools.count(0)
        self._disconnect_hooks = []

        self.of(DEFAULT_NAMESPACE)

    # ------------------------------------------------------------------ #
    # Namespaces
    # ------------------------------------------------------------------ #

    def of(self, namespace: str) -> Namespace:
        if not namespace:
            namespace = DEFAULT_NAMESPACE
        if namespace not in self._namespaces:
            self._namespaces[namespace] = Namespace(
                name=namespace, server=self
            )
        return self._namespaces[namespace]

    # ------------------------------------------------------------------ #
    # Group naming helper for rooms
    # ------------------------------------------------------------------ #

    def _group_name(self, namespace: str, room: str) -> str:
        # Make namespace and room safe for Channels group names
        ns = namespace or ""
        ns_safe = GROUP_ALLOWED_RE.sub("_", ns)
        room_safe = GROUP_ALLOWED_RE.sub("_", room)

        # Use only allowed chars in the prefix
        base = f"sio_{ns_safe}_{room_safe}"

        # Channels requires length < 100
        return base[:99]

    # ------------------------------------------------------------------ #
    # High-level broadcast API
    # ------------------------------------------------------------------ #

    async def emit(
        self,
        event: str,
        *args: Any,
        room: str | None = None,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> None:
        """
        Emit an event to:
          * all sockets in `namespace` if room is None (local only),
          * or all sockets in `room` (namespace+room), using channel layer.

        This mirrors `io.emit` / `io.to(room).emit` on the Node server.
        """
        if room is None:
            # Local broadcast (no channel layer): all sockets in this process
            for (_eio_sid, nsp), sock in list(self._sockets.items()):
                if nsp == namespace:
                    await sock.emit(event, *args)
            return

        # Room-based broadcast using channel layer groups
        pkt = SocketIOPacket(
            type=SIO_EVENT,
            namespace=namespace,
            data=[event, *args],
        )
        header, attachments = encode_packet_to_eio(pkt)
        group = self._group_name(namespace, room)

        channel_layer = get_channel_layer()
        if channel_layer is not None:
            # Broadcast to all consumers registered to this room group
            await channel_layer.group_send(
                group,
                {
                    "type": "sio.broadcast",  # handled by consumers
                    "header": header,
                    "attachments": attachments,
                },
            )

        # Additionally, send directly to any non-WebSocket sockets in this
        # process (e.g. polling-only clients), since they don't join WS-based
        # groups.
        for (_eio_sid, nsp), sock in list(self._sockets.items()):
            if nsp != namespace:
                continue
            if room not in sock.rooms:
                continue
            # If the underlying transport is not websocket, send locally
            if sock.eio._session.transport != "websocket":
                await sock.emit(event, *args)

    # ------------------------------------------------------------------ #
    # EngineIOApplication hooks (unchanged logic, shortened a bit)
    # ------------------------------------------------------------------ #

    async def on_connect(self, eio_socket: EngineIOSocket) -> None:
        self._parsers[eio_socket.sid] = SocketIOParser()

    async def on_message(
        self,
        eio_socket: EngineIOSocket,
        data: Any,
        binary: bool,
    ) -> None:
        parser = self._parsers.get(eio_socket.sid)
        if parser is None:
            return

        packets = parser.feed_eio_message(data, binary)
        for pkt in packets:
            await self._handle_sio_packet(eio_socket, pkt)

    async def on_disconnect(
        self, eio_socket: EngineIOSocket, reason: str
    ) -> None:
        sid = eio_socket.sid
        for (eio_id, _nsp_name), ns_socket in list(self._sockets.items()):
            if eio_id == sid:
                await self._on_client_disconnect(
                    ns_socket, f"engineio_{reason}"
                )
        self._parsers.pop(sid, None)

    # --------------------------------------------------------------- #
    # Hook registration API
    # --------------------------------------------------------------- #

    def register_disconnect_hook(self, hook: DisconnectHook) -> None:
        """
        Register a callback that will be invoked whenever a NamespaceSocket is
        disconnected.

        The hook must be: async def hook(ns_socket, reason: str) -> None

        """
        self._disconnect_hooks.append(hook)

    # ------------------------------------------------------------------ #
    # Packet dispatch (same as before, trimmed)
    # ------------------------------------------------------------------ #

    async def _handle_sio_packet(
        self,
        eio_socket: EngineIOSocket,
        pkt: SocketIOPacket,
    ) -> None:
        nsp_name = pkt.namespace or DEFAULT_NAMESPACE
        namespace = self._namespaces.get(nsp_name)
        if namespace is None:
            if pkt.type == SIO_CONNECT:
                await self._send_connect_error(
                    eio_socket, nsp_name, {"message": "Unknown namespace"}
                )
            return

        key = (eio_socket.sid, nsp_name)
        ns_socket = self._sockets.get(key)

        if pkt.type == SIO_CONNECT:
            if ns_socket is None:
                ns_socket = await self._create_namespace_socket(
                    eio_socket, namespace, pkt
                )
                if ns_socket is None:
                    return
                self._sockets[key] = ns_socket
            return

        if ns_socket is None:
            await eio_socket.close(reason="missing_connect")
            return

        await ns_socket._handle_packet_from_client(pkt)

    async def _create_namespace_socket(
        self,
        eio_socket: EngineIOSocket,
        nsp: Namespace,
        pkt: SocketIOPacket,
    ) -> NamespaceSocket | None:
        auth_payload = pkt.data or {}
        socket_id = f"{eio_socket.sid}#{next(self._next_socket_id)}"

        ns_socket = NamespaceSocket(
            server=self,
            eio=eio_socket,
            namespace=nsp.name,
            id=socket_id,
        )

        if nsp.connect_handler is not None:
            ok = await nsp.connect_handler(ns_socket, auth_payload)
            if not ok:
                await self._send_connect_error(
                    eio_socket,
                    nsp.name,
                    {"message": "Not authorized"},
                )
                return None

        resp = SocketIOPacket(
            type=SIO_CONNECT,
            namespace=nsp.name,
            data={"sid": socket_id},
        )
        await ns_socket._send_packet(resp)
        return ns_socket

    async def _send_connect_error(
        self,
        eio_socket: EngineIOSocket,
        nsp_name: str,
        obj: dict,
    ) -> None:
        pkt = SocketIOPacket(
            type=SIO_CONNECT_ERROR,
            namespace=nsp_name or DEFAULT_NAMESPACE,
            data=obj,
        )
        header, _attachments = encode_packet_to_eio(pkt)
        await eio_socket._send_text(header)

    async def _dispatch_event(
        self,
        socket: NamespaceSocket,
        event: str,
        args: list[Any],
        ack_cb: Callable[..., Awaitable[None]] | None,
    ) -> None:
        namespace = self._namespaces.get(socket.namespace)
        if not namespace:
            return
        handler = namespace.listeners.get(event)
        if handler is None:
            return
        await handler(socket, args, ack_cb)

    async def _on_client_disconnect(
        self,
        ns_socket: NamespaceSocket,
        reason: str,
    ) -> None:
        key = (ns_socket.eio.sid, ns_socket.namespace)
        self._sockets.pop(key, None)

        # Call all registered hooks, for example:
        # SocketIOConsumer._on_client_disconnect
        for hook in self._disconnect_hooks:
            await hook(ns_socket, reason)

        await ns_socket.leave_all()

    async def _force_disconnect_bad_packet(
        self,
        ns_socket: NamespaceSocket,
        reason: str,
    ) -> None:
        await ns_socket.eio.close(reason=reason)


_server_singleton: SocketIOServer | None = None


def get_socketio_server() -> SocketIOServer:
    global _server_singleton
    if _server_singleton is None:
        _server_singleton = SocketIOServer()
        set_engineio_app(_server_singleton)
    return _server_singleton
