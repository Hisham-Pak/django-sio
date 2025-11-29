from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .engineio import EngineIOWebSocketConsumer, LongPollingConsumer
from .socketio import (
    DEFAULT_NAMESPACE,
    Namespace,
    NamespaceSocket,
    get_socketio_server,
)

Ack = Callable[..., Awaitable[None]]


class SocketIOConsumer:
    """
    Consumer class that handles both Engine.IO transports (polling + websocket)
    and exposes a hook for subclasses to configure the Socket.IO server.

    - Mount it in routing like (for BOTH http and websocket):
        path("socket.io/", MySocketIOConsumer.as_asgi())

    - Subclass this and define:
        - `namespace = "/chat"` (optional, default "/")
        - `async def connect(self, socket, auth): ...`   # return bool
        - `async def disconnect(self, socket, reason): ...` (optional)
        - `async def event_<name>(self, socket, *args, ack=None): ...`  \
            # for SIO events

      Example:
        `event_chat_message` handles the Socket.IO event `"chat_message"`.

    """

    namespace: str = DEFAULT_NAMESPACE
    _configured: bool = False  # per subclass

    # ---------- Public: ASGI entrypoint ---------- #

    @classmethod
    def as_asgi(cls):
        """
        Channels calls this to get the ASGI app.

        This app will receive BOTH http and websocket scopes and internally
        dispatch to the proper Engine.IO transport consumer.

        """
        cls._ensure_configured()

        http_app = LongPollingConsumer.as_asgi()
        ws_app = EngineIOWebSocketConsumer.as_asgi()

        async def app(scope, receive, send):
            if scope["type"] == "http":
                return await http_app(scope, receive, send)
            elif scope["type"] == "websocket":
                return await ws_app(scope, receive, send)
            raise RuntimeError(
                f"""
                SocketIOConsumer does not handle scope type {scope["type"]!r}
                """
            )

        return app

    # ---------- Internal: wiring to SocketIOServer ---------- #

    @classmethod
    def _ensure_configured(cls) -> None:
        if cls._configured:
            return

        server = get_socketio_server()
        namespace_name = getattr(cls, "namespace", DEFAULT_NAMESPACE)
        nsp: Namespace = server.of(namespace_name)

        # CONNECT handler
        if "connect" in cls.__dict__:

            async def _connect(socket: NamespaceSocket, auth: Any) -> bool:
                # one instance per logical Socket.IO connection
                self = cls()
                socket.state["consumer"] = self
                return bool(await self.connect(socket, auth))  # type: ignore[arg-type]

            nsp.on_connect(_connect)

        # DISCONNECT hook
        async def _on_client_disconnect(
            ns_socket: NamespaceSocket, reason: str
        ):
            # Called from SocketIOServer._on_client_disconnect
            consumer = ns_socket.state.get("consumer")
            # Only handle sockets whose consumer is an instance of this class
            if consumer is None or not isinstance(consumer, cls):
                return

            if hasattr(consumer, "disconnect"):
                # user-defined: async def disconnect(
                #    self, socket: NamespaceSocket, reason: str
                # ) on consumer
                await consumer.disconnect(ns_socket, reason)  # type: ignore[call-arg]

            await ns_socket.leave_all()

        server.register_disconnect_hook(_on_client_disconnect)

        # EVENT handlers: methods named event_<name> ->
        # Socket.IO event "<name>"
        for attr_name, value in cls.__dict__.items():
            if not attr_name.startswith("event_"):
                continue
            if not callable(value):
                continue

            event_name = attr_name[len("event_") :]

            async def _handler(
                socket: NamespaceSocket,
                args: list[Any],
                ack: Ack | None,
                _method_name: str = attr_name,
            ) -> None:
                # per-connection instance
                consumer = socket.state.get("consumer")
                if consumer is None:
                    consumer = cls()
                    socket.state["consumer"] = consumer

                method = getattr(consumer, _method_name)

                # We allow two signatures:
                #   async def event_x(self, socket, *args)
                #   async def event_x(self, socket, *args, ack=None)
                if "ack" in method.__code__.co_varnames:
                    await method(socket, *args, ack=ack)
                else:
                    await method(socket, *args)
                    if ack is not None:
                        await ack()

            nsp.on(event_name)(_handler)

        cls._configured = True
