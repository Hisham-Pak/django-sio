# engineio/app.py
from __future__ import annotations

import logging

from .packets import encode_http_binary_message, encode_text_packet
from .session import EngineIOSession, destroy_session

logger = logging.getLogger("sio." + __name__)


class EngineIOSocket:
    """
    Public API object representing a single Engine.IO connection (session).

    This is what Socket.IO implementation will primarily interact with.
    """

    def __init__(self, session: EngineIOSession):
        self._session = session
        logger.debug("EngineIOSocket created for sid=%s", session.sid)

    @property
    def sid(self) -> str:
        return self._session.sid

    async def send(self, data: str | bytes) -> None:
        """
        Send a *message* packet (type 4) to the client.
        """
        logger.debug(
            "EngineIOSocket.send sid=%s binary=%s len=%s",
            self.sid,
            isinstance(data, (bytes, bytearray, memoryview)),
            len(data) if data is not None else 0,
        )
        if isinstance(data, bytes):
            await self._send_binary(data)
        else:
            await self._send_text(str(data))

    async def _send_text(self, text: str) -> None:
        session = self._session
        logger.debug(
            "EngineIOSocket._send_text sid=%s transport=%s text_preview=%r",
            session.sid,
            session.transport,
            text[:200],
        )
        segment = encode_text_packet("4", text)

        if session.transport == "websocket" and session.websocket is not None:
            logger.debug(
                "Sending Engine.IO text message over WebSocket sid=%s",
                session.sid,
            )
            await session.websocket.send(text_data=segment)
        else:
            logger.debug(
                "Enqueuing Engine.IO text message for HTTP polling sid=%s",
                session.sid,
            )
            await session.enqueue_http_packet(segment)

    async def _send_binary(self, data: bytes) -> None:
        session = self._session
        logger.debug(
            "EngineIOSocket._send_binary sid=%s transport=%s bytes=%d",
            session.sid,
            session.transport,
            len(data),
        )

        if session.transport == "websocket" and session.websocket is not None:
            # WebSocket binary frame: <type-byte><binary-data>
            frame = b"4" + data
            logger.debug(
                "Sending Engine.IO binary message over WebSocket sid=%s bytes=%d",
                session.sid,
                len(frame),
            )
            await session.websocket.send(bytes_data=frame)
        else:
            # HTTP long-polling: base64 + 'b' prefix, per spec.
            segment = encode_http_binary_message(data)
            logger.debug(
                "Enqueuing Engine.IO binary message for HTTP polling sid=%s segment_len=%d",
                session.sid,
                len(segment),
            )
            await session.enqueue_http_packet(segment)

    async def close(self, reason: str = "server_close") -> None:
        """
        Close this Engine.IO session from application code.
        """
        session = self._session
        logger.info(
            "EngineIOSocket.close requested sid=%s reason=%s",
            session.sid,
            reason,
        )

        # If we have a websocket, closing it will trigger the disconnect
        # handler, which will in turn call close_session().
        if session.websocket is not None:
            logger.debug(
                "Closing underlying WebSocket for sid=%s", session.sid
            )
            await session.websocket.close()
        else:
            await close_session(session, reason=reason)


class EngineIOApplication:
    """
    Application callback interface.

    Override this to build higher-level protocols (Socket.IO, your own, etc).
    """

    async def on_connect(self, socket: EngineIOSocket) -> None:
        logger.info("EngineIOApplication.on_connect sid=%s", socket.sid)

    async def on_message(
        self,
        socket: EngineIOSocket,
        data: str | bytes,
        binary: bool,
    ) -> None:
        # Default behaviour: echo (so you can run Engine.IO test-suite).
        logger.debug(
            "EngineIOApplication.on_message sid=%s binary=%s len=%s",
            socket.sid,
            binary,
            len(data) if data is not None else 0,
        )
        await socket.send(data)

    async def on_disconnect(self, socket: EngineIOSocket, reason: str) -> None:
        logger.info(
            "EngineIOApplication.on_disconnect sid=%s reason=%s",
            socket.sid,
            reason,
        )


_engineio_app: EngineIOApplication = EngineIOApplication()


def set_engineio_app(app: EngineIOApplication) -> None:
    """
    Register a global Engine.IO application instance.

    Call this at startup (e.g. in Django AppConfig.ready()).
    """
    global _engineio_app
    logger.info("Engine.IO application instance set to %r", app)
    _engineio_app = app


def get_engineio_app() -> EngineIOApplication:
    logger.debug("get_engineio_app called")
    return _engineio_app


def get_or_create_socket(session: EngineIOSession) -> EngineIOSocket:
    if session.app_socket is None:
        logger.debug("Creating EngineIOSocket for sid=%s", session.sid)
        session.app_socket = EngineIOSocket(session)
    return session.app_socket


async def close_session(
    session: EngineIOSession, reason: str = "server_close"
) -> None:
    """
    Close a session and notify the application (idempotent).
    """
    logger.info(
        "close_session called sid=%s reason=%s closed=%s",
        session.sid,
        reason,
        session.closed,
    )
    if session.closed:
        logger.debug(
            "Session already closed sid=%s, ensuring removal from registry",
            session.sid,
        )
        await destroy_session(session.sid)
        return

    # Push an Engine.IO "noop" packet (type "6") into the HTTP queue.
    # If a client has a long-poll GET blocked in http_next_payload(),
    # this wakes it up so it can respond and the ASGI task can exit cleanly.
    logger.debug(
        "Enqueue Engine.IO noop (6) before closing session sid=%s", session.sid
    )
    await session.enqueue_http_packet("6")

    session.closed = True
    socket = get_or_create_socket(session)
    app = get_engineio_app()

    try:
        await app.on_disconnect(socket, reason)
    finally:
        logger.debug("Destroying Engine.IO session sid=%s", session.sid)
        await destroy_session(session.sid)
