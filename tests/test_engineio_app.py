from __future__ import annotations

import pytest

from sio.engineio.app import (
    EngineIOApplication,
    EngineIOSocket,
    close_session,
    get_engineio_app,
    set_engineio_app,
)
from sio.engineio.packets import decode_http_payload
from sio.engineio.session import (
    EngineIOSession,
    create_session,
)


class RecordingApp(EngineIOApplication):
    def __init__(self):
        self.connected = []
        self.disconnected = []
        self.messages = []

    async def on_connect(self, socket: EngineIOSocket) -> None:
        self.connected.append(socket.sid)

    async def on_message(self, socket, data, binary):
        self.messages.append((socket.sid, data, binary))

    async def on_disconnect(self, socket, reason: str) -> None:
        self.disconnected.append((socket.sid, reason))


@pytest.mark.asyncio
async def test_set_and_get_engineio_app():
    app = RecordingApp()
    set_engineio_app(app)
    assert get_engineio_app() is app


@pytest.mark.asyncio
async def test_engineio_socket_send_polling_text_and_binary():
    sess = EngineIOSession("sid")
    sock = EngineIOSocket(sess)

    await sock.send("hello")
    await sock.send(b"\x01\x02")

    payload = await sess.http_next_payload(timeout=0.1)
    packets = decode_http_payload(payload)

    assert len(packets) == 2
    assert packets[0].data == "hello"
    assert not packets[0].binary
    assert packets[1].data == b"\x01\x02"
    assert packets[1].binary


@pytest.mark.asyncio
async def test_engineio_socket_send_websocket_text_and_binary():
    sess = EngineIOSession("sid")
    sess.transport = "websocket"

    class DummyWS:
        def __init__(self):
            self.sent_text = []
            self.sent_bytes = []

        async def send(self, text_data=None, bytes_data=None):
            if text_data is not None:
                self.sent_text.append(text_data)
            if bytes_data is not None:
                self.sent_bytes.append(bytes_data)

    ws = DummyWS()
    sess.websocket = ws

    sock = EngineIOSocket(sess)
    await sock.send("hello")
    await sock.send(b"\x01\x02")

    assert ws.sent_text == ["4hello"]
    assert ws.sent_bytes == [b"\x01\x02"]


@pytest.mark.asyncio
async def test_engineio_socket_close_with_and_without_websocket(monkeypatch):
    # case 1: websocket present -> websocket.close() is called, not
    # close_session
    sess1 = EngineIOSession("sid1")

    closed = []

    class DummyWS:
        async def close(self):
            closed.append("ws_close")

    sess1.websocket = DummyWS()

    sock1 = EngineIOSocket(sess1)
    await sock1.close()
    assert closed == ["ws_close"]
    # logical close is handled by websocket consumer; we don't assert it here

    # case 2: no websocket -> close_session(session, ...) branch
    sess2 = EngineIOSession("sid2")

    called = {}

    async def fake_close_session(session, reason="server_close"):
        called["sid"] = session.sid
        called["reason"] = reason

    from sio.engineio import app as app_mod

    monkeypatch.setattr(app_mod, "close_session", fake_close_session)

    sock2 = EngineIOSocket(sess2)
    await sock2.close(reason="custom")
    assert called == {"sid": "sid2", "reason": "custom"}


@pytest.mark.asyncio
async def test_close_session_branches(monkeypatch):
    # closed=True branch just destroys session
    sess_closed = EngineIOSession("sid_closed")
    sess_closed.closed = True

    destroyed = []

    async def fake_destroy(sid: str):
        destroyed.append(sid)

    import sio.engineio.app as app_mod

    monkeypatch.setattr(app_mod, "destroy_session", fake_destroy)

    await close_session(sess_closed)
    assert destroyed == ["sid_closed"]

    # not closed branch: enqueue noop, mark closed, call app.on_disconnect,
    # then destroy
    app = RecordingApp()
    set_engineio_app(app)

    sess = await create_session()
    sid = sess.sid

    destroyed.clear()
    monkeypatch.setattr(app_mod, "destroy_session", fake_destroy)

    await close_session(sess, reason="bye")

    # noop ("6") must be queued
    payload = await sess.http_next_payload(timeout=0.1)
    assert payload.decode("utf-8") == "6"

    # logical flag
    assert sess.closed is True

    # app disconnect hook
    assert app.disconnected == [(sid, "bye")]

    # session removed
    assert destroyed == [sid]


class DummySocket:
    """
    Minimal stand-in for EngineIOSocket with just a .send() method.

    We don't care about actual transport; we only want to see what
    EngineIOApplication.on_message asks the socket to send.

    """
    def __init__(self) -> None:
        # needed because logging uses socket.sid
        self.sid = "dummy-sid"
        self.sent: list[object] = []

    async def send(self, data):
        self.sent.append(data)


@pytest.mark.asyncio
async def test_engineio_application_on_connect_and_disconnect_are_noop():
    """
    The default EngineIOApplication.on_connect/on_disconnect implementations do
    nothing and should be awaitable without side effects.
    """
    app = EngineIOApplication()
    socket = DummySocket()

    # Should not raise or modify socket
    await app.on_connect(socket)
    await app.on_disconnect(socket, reason="whatever")

    assert socket.sent == []  # nothing was sent implicitly


@pytest.mark.asyncio
async def test_engineio_application_on_message_echoes_text_and_binary():
    """
    The default on_message implementation should simply echo the incoming data
    back via socket.send(data), regardless of the 'binary' flag.
    """
    app = EngineIOApplication()
    socket = DummySocket()

    # Text payload
    await app.on_message(socket, "hello", binary=False)
    # Binary payload
    await app.on_message(socket, b"\x01\x02", binary=True)

    assert socket.sent == ["hello", b"\x01\x02"]
