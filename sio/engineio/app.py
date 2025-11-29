from __future__ import annotations

from .packets import encode_http_binary_message, encode_text_packet
from .session import EngineIOSession, destroy_session


class EngineIOSocket:
    """
    Public API object representing a single Engine.IO connection (session).

    This is what Socket.IO implementation will primarily interact with.

    """

    def __init__(self, session: EngineIOSession):
        self._session = session

    @property
    def sid(self) -> str:
        return self._session.sid

    async def send(self, data: str | bytes) -> None:
        """
        Send a *message* packet (type 4) to the client.
        """
        if isinstance(data, bytes):
            await self._send_binary(data)
        else:
            await self._send_text(str(data))

    async def _send_text(self, text: str) -> None:
        session = self._session
        segment = encode_text_packet("4", text)

        if session.transport == "websocket" and session.websocket is not None:
            # WebSocket text frame: "4<text>"
            await session.websocket.send(text_data=segment)
        else:
            # HTTP polling: queue segment for next GET
            await session.enqueue_http_packet(segment)

    async def _send_binary(self, data: bytes) -> None:
        session = self._session

        if session.transport == "websocket" and session.websocket is not None:
            # WebSocket binary frame: <type-byte><binary-data>
            frame = b"4" + data
            await session.websocket.send(bytes_data=frame)
        else:
            # HTTP long-polling: base64 + 'b' prefix, per spec.
            segment = encode_http_binary_message(data)
            await session.enqueue_http_packet(segment)

    async def close(self, reason: str = "server_close") -> None:
        """
        Close this Engine.IO session from application code.
        """
        session = self._session

        # If we have a websocket, closing it will trigger the disconnect
        # handler, which will in turn call close_session().
        if session.websocket is not None:
            await session.websocket.close()
        else:
            await close_session(session, reason=reason)


class EngineIOApplication:
    """
    Application callback interface.

    Override this to build higher-level protocols (Socket.IO, your own, etc).

    """

    async def on_connect(self, socket: EngineIOSocket) -> None:
        pass

    async def on_message(
        self,
        socket: EngineIOSocket,
        data: str | bytes,
        binary: bool,
    ) -> None:
        # Default behaviour: echo (so you can run Engine.IO test-suite).
        await socket.send(data)

    async def on_disconnect(self, socket: EngineIOSocket, reason: str) -> None:
        pass


_engineio_app: EngineIOApplication = EngineIOApplication()


def set_engineio_app(app: EngineIOApplication) -> None:
    """
    Register a global Engine.IO application instance.

    Call this at startup (e.g. in Django AppConfig.ready()).

    """
    global _engineio_app
    _engineio_app = app


def get_engineio_app() -> EngineIOApplication:
    return _engineio_app


def get_or_create_socket(session: EngineIOSession) -> EngineIOSocket:
    if session.app_socket is None:
        session.app_socket = EngineIOSocket(session)
    return session.app_socket


async def close_session(
    session: EngineIOSession, reason: str = "server_close"
) -> None:
    """
    Close a session and notify the application (idempotent).
    """
    if session.closed:
        # Already closed/logically dead; just ensure it's not in registry.
        await destroy_session(session.sid)
        return

    # Push an Engine.IO "noop" packet (type "6") into the HTTP queue.
    # If a client has a long-poll GET blocked in http_next_payload(),
    # this wakes it up so it can respond and the ASGI task can exit cleanly.
    await session.enqueue_http_packet("6")

    session.closed = True
    socket = get_or_create_socket(session)
    app = get_engineio_app()

    try:
        await app.on_disconnect(socket, reason)
    finally:
        await destroy_session(session.sid)
