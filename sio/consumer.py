# consumer.py (root package)
from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from .engineio import EngineIOWebSocketConsumer, LongPollingConsumer
from .socketio import (
    DEFAULT_NAMESPACE,
    Namespace,
    NamespaceSocket,
    get_socketio_server,
)

Ack = Callable[..., Awaitable[None]]

logger = logging.getLogger("sio." + __name__)


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
        - `async def event_<name>(self, socket, *args, ack=None): ...`
            for SIO events

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
        logger.info(
            "SocketIOConsumer.as_asgi called for %s namespace=%s",
            cls.__name__,
            getattr(cls, "namespace", DEFAULT_NAMESPACE),
        )
        cls._ensure_configured()

        http_app = LongPollingConsumer.as_asgi()
        ws_app = EngineIOWebSocketConsumer.as_asgi()

        async def app(scope, receive, send):
            scope_type = scope.get("type")
            path = scope.get("path")
            logger.debug(
                "SocketIOConsumer app invoked type=%s path=%s cls=%s",
                scope_type,
                path,
                cls.__name__,
            )
            if scope_type == "http":
                return await http_app(scope, receive, send)
            elif scope_type == "websocket":
                return await ws_app(scope, receive, send)

            logger.warning(
                """
                SocketIOConsumer does not handle scope type %r path=%s cls=%s
                """,
                scope_type,
                path,
                cls.__name__,
            )
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
            logger.debug(
                "SocketIOConsumer %s already configured, skipping",
                cls.__name__,
            )
            return

        logger.info("Configuring SocketIOConsumer %s", cls.__name__)

        server = get_socketio_server()
        namespace_name = getattr(cls, "namespace", DEFAULT_NAMESPACE)
        nsp: Namespace = server.of(namespace_name)

        logger.debug(
            "Using namespace=%s for consumer class=%s",
            namespace_name,
            cls.__name__,
        )

        # CONNECT handler
        if "connect" in cls.__dict__:
            logger.debug(
                "Registering connect handler for consumer=%s namespace=%s",
                cls.__name__,
                namespace_name,
            )

            async def _connect(socket: NamespaceSocket, auth: Any) -> bool:
                # one instance per logical Socket.IO connection
                logger.info(
                    """
                    SocketIOConsumer.connect invoked cls=%s socket_id=%s ns=%s
                    auth_type=%s
                    """,
                    cls.__name__,
                    socket.id,
                    socket.namespace,
                    type(auth).__name__,
                )
                self = cls()
                socket.state["consumer"] = self
                result = bool(await self.connect(socket, auth))  # type: ignore[arg-type]
                logger.debug(
                    """
                    SocketIOConsumer.connect result cls=%s socket_id=%s ns=%s
                    accepted=%s
                    """,
                    cls.__name__,
                    socket.id,
                    socket.namespace,
                    result,
                )
                return result

            nsp.on_connect(_connect)
        else:
            logger.debug(
                "No connect method on consumer=%s, skipping connect handler",
                cls.__name__,
            )

        # DISCONNECT hook
        async def _on_client_disconnect(
            ns_socket: NamespaceSocket, reason: str
        ):
            # Called from SocketIOServer._on_client_disconnect
            consumer = ns_socket.state.get("consumer")

            logger.info(
                """
                Disconnect hook triggered for socket_id=%s ns=%s reason=%s
                consumer_type=%s
                """,
                ns_socket.id,
                ns_socket.namespace,
                reason,
                type(consumer).__name__ if consumer is not None else None,
            )

            # Only handle sockets whose consumer is an instance of this class
            if consumer is None or not isinstance(consumer, cls):
                logger.debug(
                    """
                    Disconnect hook ignored: consumer mismatch for socket_id=%s
                    ns=%s
                    """,
                    ns_socket.id,
                    ns_socket.namespace,
                )
                return

            if hasattr(consumer, "disconnect"):
                logger.debug(
                    """
                    Calling consumer.disconnect for socket_id=%s ns=%s cls=%s
                    """,
                    ns_socket.id,
                    ns_socket.namespace,
                    cls.__name__,
                )
                # user-defined: async def disconnect(self, socket, reason)
                await consumer.disconnect(  # type: ignore[call-arg]
                    ns_socket, reason
                )

            logger.debug(
                "Leaving all rooms on disconnect for socket_id=%s ns=%s",
                ns_socket.id,
                ns_socket.namespace,
            )
            await ns_socket.leave_all()

        server.register_disconnect_hook(_on_client_disconnect)
        logger.debug(
            """
            Registered disconnect hook for consumer=%s namespace=%s
            """,
            cls.__name__,
            namespace_name,
        )

        # EVENT handlers: methods named event_<name> ->
        # Socket.IO event "<name>"
        for attr_name, value in cls.__dict__.items():
            if not attr_name.startswith("event_"):
                continue
            if not callable(value):
                continue

            event_name = attr_name[len("event_") :]

            logger.debug(
                "Registering event handler event=%s method=%s.%s",
                event_name,
                cls.__name__,
                attr_name,
            )

            async def _handler(
                socket: NamespaceSocket,
                args: list[Any],
                ack: Ack | None,
                _method_name: str = attr_name,
                _event_name: str = event_name,
            ) -> None:
                # per-connection instance
                consumer = socket.state.get("consumer")
                if consumer is None:
                    logger.debug(
                        """
                        No consumer instance in state for socket_id=%s ns=%s,
                        creating new %s
                        """,
                        socket.id,
                        socket.namespace,
                        cls.__name__,
                    )
                    consumer = cls()
                    socket.state["consumer"] = consumer

                method = getattr(consumer, _method_name)

                logger.info(
                    """
                    Handling Socket.IO event=%s method=%s.%s socket_id=%s
                    ns=%s args_count=%d has_ack=%s
                    """,
                    _event_name,
                    cls.__name__,
                    _method_name,
                    socket.id,
                    socket.namespace,
                    len(args),
                    ack is not None,
                )

                # We allow two signatures:
                #   async def event_x(self, socket, *args)
                #   async def event_x(self, socket, *args, ack=None)
                if "ack" in method.__code__.co_varnames:
                    logger.debug(
                        """
                        Calling event handler with ack parameter for event=%s
                        method=%s.%s
                        """,
                        _event_name,
                        cls.__name__,
                        _method_name,
                    )
                    await method(socket, *args, ack=ack)
                else:
                    logger.debug(
                        """
                        Calling event handler without ack parameter for
                        event=%s method=%s.%s
                        """,
                        _event_name,
                        cls.__name__,
                        _method_name,
                    )
                    await method(socket, *args)
                    if ack is not None:
                        logger.debug(
                            """
                            Sending default ack() for event=%s socket_id=%s
                            ns=%s
                            """,
                            _event_name,
                            socket.id,
                            socket.namespace,
                        )
                        await ack()

            nsp.on(event_name)(_handler)

        cls._configured = True
        logger.info(
            "SocketIOConsumer configuration completed cls=%s namespace=%s",
            cls.__name__,
            namespace_name,
        )
