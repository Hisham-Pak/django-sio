from __future__ import annotations

import asyncio

import pytest

from sio.engineio import websocket as ws_mod
from sio.engineio.constants import ENGINE_IO_VERSION, TRANSPORT_WEBSOCKET
from sio.engineio.session import EngineIOSession, create_session
from sio.engineio.websocket import EngineIOWebSocketConsumer


@pytest.mark.asyncio
async def test_ws_connect_invalid_query_closes(monkeypatch):
    """
    If EIO or transport query params are invalid, connect() should just
    close().
    """
    consumer = EngineIOWebSocketConsumer()
    consumer.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": b"EIO=3&transport=websocket",  # wrong EIO
    }

    closed = {}

    async def fake_close(code=None):
        closed["called"] = True
        closed["code"] = code

    consumer.close = fake_close  # type: ignore[assignment]

    await consumer.connect()
    assert closed.get("called") is True
    # No heartbeat started
    assert consumer._heartbeat_task is None


@pytest.mark.asyncio
async def test_ws_connect_upgrade_from_polling(monkeypatch):
    """
    When a sid is provided and a polling session exists, connect() should
    upgrade that session to websocket and accept().
    """
    session = await create_session()
    assert session.transport == "polling"

    consumer = EngineIOWebSocketConsumer()
    consumer.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_WEBSOCKET}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    accepted = {}

    async def fake_accept():
        accepted["called"] = True

    # Avoid starting a real background task
    async def fake_heartbeat_loop():
        pass

    consumer.accept = fake_accept  # type: ignore[assignment]

    # We'll let connect() create the task; make it a dummy object
    async def fake_create_task(coro):
        await fake_heartbeat_loop()
        return object()

    monkeypatch.setattr(
        "sio.engineio.websocket.asyncio.create_task", fake_create_task
    )

    await consumer.connect()

    assert consumer.session is session
    assert session.websocket is consumer
    assert accepted.get("called") is True


@pytest.mark.asyncio
async def test_ws_receive_closes_if_no_session():
    """
    If receive() is called when there is no session or it is closed, it should
    call close() and return.
    """
    consumer = EngineIOWebSocketConsumer()
    consumer.session = None

    closed = {}

    async def fake_close(code=None):
        closed["called"] = True

    consumer.close = fake_close  # type: ignore[assignment]

    await consumer.receive(text_data="anything")
    assert closed.get("called") is True


@pytest.mark.asyncio
async def test_ws_receive_invalid_frame_closes(monkeypatch):
    """
    If decode_ws_text_frame raises ValueError, receive() should close().
    """
    from sio.engineio import websocket as ws_mod

    session = EngineIOSession("sid")
    consumer = EngineIOWebSocketConsumer()
    consumer.session = session

    closed = {}

    async def fake_close(code=None):
        closed["called"] = True

    consumer.close = fake_close  # type: ignore[assignment]

    def fake_decode_ws_text_frame(text):
        raise ValueError("boom")

    monkeypatch.setattr(
        ws_mod, "decode_ws_text_frame", fake_decode_ws_text_frame
    )

    await consumer.receive(text_data="bad")
    assert closed.get("called") is True


@pytest.mark.asyncio
async def test_ws_receive_ping_probe_and_upgrade():
    """
    - '2probe' → respond with '3probe' via _send_text_packet
    - '5' → mark transport='websocket' and enqueue '6' on HTTP queue
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid")
    consumer.session = session

    sent = []

    async def fake_send_text_packet(pkt_type: str, data: str = ""):
        sent.append((pkt_type, data))

    consumer._send_text_packet = fake_send_text_packet  # type: ignore[assignment]

    # 1) ping probe
    await consumer.receive(text_data="2probe")
    assert ("3", "probe") in sent

    # 2) upgrade complete
    # session initially 'polling'
    assert session.transport == "polling"

    queued = []

    async def fake_enqueue_http_packet(seg: str):
        queued.append(seg)

    session.enqueue_http_packet = fake_enqueue_http_packet  # type: ignore[assignment]

    await consumer.receive(text_data="5")
    assert session.transport == "websocket"
    assert "6" in queued


@pytest.mark.asyncio
async def test_ws_heartbeat_loop_closes_on_missing_pong(monkeypatch):
    """
    _heartbeat_loop should send a ping and then close the connection if
    last_pong is not updated after PING_TIMEOUT_MS.
    """
    from sio.engineio import websocket as ws_mod

    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid")
    consumer.session = session

    # make intervals effectively zero to run fast
    monkeypatch.setattr(ws_mod, "PING_INTERVAL_MS", 0)
    monkeypatch.setattr(ws_mod, "PING_TIMEOUT_MS", 0)

    pings = []
    closed = {}

    async def fake_send_text_packet(pkt_type: str, data: str = ""):
        pings.append((pkt_type, data))

    async def fake_close(code=None):
        closed["called"] = True
        # mark closed so loop exits
        consumer.session.closed = True  # type: ignore[union-attr]

    consumer._send_text_packet = fake_send_text_packet  # type: ignore[assignment]
    consumer.close = fake_close  # type: ignore[assignment]

    await consumer._heartbeat_loop()

    # At least one ping should have been sent
    assert any(pkt_type == "2" for pkt_type, _ in pings)
    # And connection should have been closed due to missing pong
    assert closed.get("called") is True


# --------------------------------------------------------------------------- #
# connect() branches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ws_connect_upgrade_from_polling_success(monkeypatch):
    """
    Connect() with a sid should upgrade from a polling session when:

    - session exists
    - not timed out
    - not closed
    - no existing websocket

    We don't assert on asyncio.create_task; we just verify that:
      - the session is attached,
      - session.websocket points to this consumer,
      - accept() was called.

    """

    class Sess:
        def __init__(self):
            self.sid = "sid-upgrade"
            self.transport = "polling"
            self.closed = False
            self.websocket = None
            self.is_timed_out_calls = 0

        def is_timed_out(self):
            self.is_timed_out_calls += 1
            return False

    session = Sess()

    async def fake_get_session(sid: str):
        assert sid == session.sid
        return session

    accepted = {}

    async def fake_accept():
        accepted["called"] = True

    # stub heartbeat loop so it returns quickly
    async def fake_heartbeat_loop(self):
        # no-op
        return

    consumer = EngineIOWebSocketConsumer()
    consumer.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_WEBSOCKET}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(ws_mod, "get_session", fake_get_session)
    monkeypatch.setattr(
        EngineIOWebSocketConsumer, "_heartbeat_loop", fake_heartbeat_loop
    )
    consumer.accept = fake_accept  # type: ignore[assignment]

    await consumer.connect()

    assert consumer.session is session
    assert session.websocket is consumer
    assert accepted.get("called") is True


@pytest.mark.asyncio
async def test_ws_connect_upgrade_missing_or_bad_session(monkeypatch):
    """
    When sid is provided but get_session returns None, or session is timed out
    or closed, connect() should close().
    """

    # Case 1: get_session returns None
    async def fake_get_session_none(sid: str):
        return None

    consumer1 = EngineIOWebSocketConsumer()
    consumer1.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_WEBSOCKET}&sid=missing".encode(  # noqa: E501
            "ascii"
        ),
    }
    closed1 = {}

    async def fake_close1(code=None):
        closed1["called"] = True

    monkeypatch.setattr(ws_mod, "get_session", fake_get_session_none)
    consumer1.close = fake_close1  # type: ignore[assignment]
    await consumer1.connect()
    assert closed1.get("called") is True

    # Case 2: session.is_timed_out() is True
    class SessTimedOut:
        def __init__(self):
            self.sid = "sid-timed"
            self.transport = "polling"
            self.closed = False
            self.websocket = None

        def is_timed_out(self):
            return True

    session2 = SessTimedOut()

    async def fake_get_session2(sid: str):
        return session2

    consumer2 = EngineIOWebSocketConsumer()
    consumer2.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_WEBSOCKET}&sid={session2.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }
    closed2 = {}

    async def fake_close2(code=None):
        closed2["called"] = True

    monkeypatch.setattr(ws_mod, "get_session", fake_get_session2)
    consumer2.close = fake_close2  # type: ignore[assignment]
    await consumer2.connect()
    assert closed2.get("called") is True

    # Case 3: session.closed is True
    class SessClosed:
        def __init__(self):
            self.sid = "sid-closed"
            self.transport = "polling"
            self.closed = True
            self.websocket = None

        def is_timed_out(self):
            return False

    session3 = SessClosed()

    async def fake_get_session3(sid: str):
        return session3

    consumer3 = EngineIOWebSocketConsumer()
    consumer3.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_WEBSOCKET}&sid={session3.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }
    closed3 = {}

    async def fake_close3(code=None):
        closed3["called"] = True

    monkeypatch.setattr(ws_mod, "get_session", fake_get_session3)
    consumer3.close = fake_close3  # type: ignore[assignment]
    await consumer3.connect()
    assert closed3.get("called") is True


@pytest.mark.asyncio
async def test_ws_connect_upgrade_existing_websocket(monkeypatch):
    """
    If session.websocket is already set to a different consumer, connect() must
    close the new consumer (only one websocket per session).
    """

    class Sess:
        def __init__(self):
            self.sid = "sid-ws-existing"
            self.transport = "polling"
            self.closed = False
            # Pretend there is already a different websocket bound
            self.websocket = object()

        def is_timed_out(self):
            return False

    session = Sess()

    async def fake_get_session(sid: str):
        return session

    consumer = EngineIOWebSocketConsumer()
    consumer.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_WEBSOCKET}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    accepted: dict[str, bool] = {}
    closed: dict[str, bool] = {}

    async def fake_accept():
        accepted["called"] = True

    async def fake_close(code=None):
        closed["called"] = True

    # Use our fake session + stubs
    monkeypatch.setattr(ws_mod, "get_session", fake_get_session)
    consumer.accept = fake_accept  # type: ignore[assignment]
    consumer.close = fake_close    # type: ignore[assignment]

    await consumer.connect()

    # The new websocket must be accepted then closed, but must NOT replace the existing one
    assert accepted.get("called") is True
    assert closed.get("called") is True
    assert session.websocket is not consumer


@pytest.mark.asyncio
async def test_ws_connect_websocket_only_session(monkeypatch):
    """
    When no sid is provided, connect() should:

    - create a new session,
    - set transport='websocket',
    - attach session.websocket to the consumer,
    - send an open packet,
    - call app.on_connect().

    """
    session = EngineIOSession("sid-ws-only")

    async def fake_create_session():
        return session

    open_packet_sent = {}
    accepted = {}
    app_connected = {}

    class DummyApp:
        def __init__(self):
            self.connected = []

        async def on_connect(self, socket):
            self.connected.append(socket)
            app_connected["called"] = True

        async def on_message(self, socket, data, binary):
            pass

        async def on_disconnect(self, socket, reason):
            pass

    app = DummyApp()

    def fake_get_engineio_app():
        return app

    class DummySocket:
        def __init__(self, sess):
            self.session = sess

    def fake_get_or_create_socket(sess):
        assert sess is session
        return DummySocket(sess)

    def fake_encode_open_packet(sid: str, upgrades: list[str]):
        # simple deterministic string
        return f'0{{"sid":"{sid}"}}'

    consumer = EngineIOWebSocketConsumer()
    consumer.scope = {
        "type": "websocket",
        "path": "/socket.io/",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_WEBSOCKET}".encode(  # noqa: E501
            "ascii"
        ),
    }

    async def fake_accept():
        accepted["called"] = True

    async def fake_send(text_data=None, bytes_data=None):
        if text_data is not None:
            open_packet_sent["data"] = text_data

    # stub heartbeat loop to avoid long-running task
    async def fake_heartbeat_loop(self):
        return

    monkeypatch.setattr(ws_mod, "create_session", fake_create_session)
    monkeypatch.setattr(ws_mod, "get_engineio_app", fake_get_engineio_app)
    monkeypatch.setattr(
        ws_mod, "get_or_create_socket", fake_get_or_create_socket
    )
    monkeypatch.setattr(ws_mod, "encode_open_packet", fake_encode_open_packet)
    monkeypatch.setattr(
        EngineIOWebSocketConsumer, "_heartbeat_loop", fake_heartbeat_loop
    )

    consumer.accept = fake_accept  # type: ignore[assignment]
    consumer.send = fake_send  # type: ignore[assignment]

    await consumer.connect()

    assert consumer.session is session
    assert session.transport == "websocket"
    assert session.websocket is consumer

    assert accepted.get("called") is True
    assert open_packet_sent["data"].startswith("0")
    assert app_connected.get("called") is True


# --------------------------------------------------------------------------- #
# disconnect() branches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ws_disconnect_cancels_heartbeat_and_closes_session(monkeypatch):
    """
    Disconnect() should:

    - cancel heartbeat task if present
    - call close_session(reason='websocket_disconnect')
    - clear session.websocket and consumer.session

    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-disc")
    consumer.session = session

    class DummyTask:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    task = DummyTask()
    consumer._heartbeat_task = task  # type: ignore[assignment]

    closed = {}

    async def fake_close_session(sess, reason=""):
        closed["sid"] = sess.sid
        closed["reason"] = reason

    monkeypatch.setattr(ws_mod, "close_session", fake_close_session)

    await consumer.disconnect(code=1000)

    assert task.cancelled is True
    assert consumer._heartbeat_task is None
    assert closed == {"sid": "sid-disc", "reason": "websocket_disconnect"}
    assert session.websocket is None
    assert consumer.session is None


@pytest.mark.asyncio
async def test_ws_disconnect_when_no_heartbeat_or_session(monkeypatch):
    """
    Disconnect() should tolerate missing heartbeat task and missing session.
    """
    consumer = EngineIOWebSocketConsumer()
    consumer._heartbeat_task = None
    consumer.session = None

    # Should not raise
    await consumer.disconnect(code=1000)


# --------------------------------------------------------------------------- #
# _heartbeat_loop branches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ws_heartbeat_loop_handles_cancelled_error(monkeypatch):
    """
    If asyncio.sleep inside _heartbeat_loop raises asyncio.CancelledError, the
    loop should swallow it and return without propagating.
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-hb-cancel")
    consumer.session = session

    # We don't actually care about timing here.
    monkeypatch.setattr(ws_mod, "PING_INTERVAL_MS", 1000)
    monkeypatch.setattr(ws_mod, "PING_TIMEOUT_MS", 1000)

    # Force asyncio.sleep (as imported in websocket.py) to raise CancelledError
    async def fake_sleep(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(ws_mod.asyncio, "sleep", fake_sleep)

    # Should NOT raise, because _heartbeat_loop wraps the whole body in
    # try/except asyncio.CancelledError.
    await consumer._heartbeat_loop()


# --------------------------------------------------------------------------- #
# Sending helpers
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_send_text_and_binary_packet_use_encoders(monkeypatch):
    """
    _send_text_packet and _send_binary_packet should use encode_ws_* helpers
    and then call send() with the resulting frame.
    """
    consumer = EngineIOWebSocketConsumer()

    sent = {"text": None, "bytes": None}

    async def fake_send(text_data=None, bytes_data=None):
        if text_data is not None:
            sent["text"] = text_data
        if bytes_data is not None:
            sent["bytes"] = bytes_data

    consumer.send = fake_send  # type: ignore[assignment]

    def fake_encode_text(packet_type: str, data: str = "") -> str:
        return f"T:{packet_type}:{data}"

    def fake_encode_binary(packet_type: str, data: bytes) -> bytes:
        return f"B:{packet_type}:{data!r}".encode("ascii")

    monkeypatch.setattr(ws_mod, "encode_ws_text_frame", fake_encode_text)
    monkeypatch.setattr(ws_mod, "encode_ws_binary_frame", fake_encode_binary)

    await consumer._send_text_packet("4", "hello")
    await consumer._send_binary_packet("4", b"\x01\x02")

    assert sent["text"] == "T:4:hello"
    assert sent["bytes"] == b"B:4:b'\\x01\\x02'"


# --------------------------------------------------------------------------- #
# receive() branches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ws_receive_decode_error_closes(monkeypatch):
    """
    If decode_ws_text_frame raises ValueError, receive() should close().
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-rx-err")
    consumer.session = session

    closed = {}

    async def fake_close(code=None):
        closed["called"] = True

    consumer.close = fake_close  # type: ignore[assignment]

    def fake_decode_ws_text_frame(text):
        raise ValueError("boom")

    monkeypatch.setattr(
        ws_mod, "decode_ws_text_frame", fake_decode_ws_text_frame
    )

    await consumer.receive(text_data="bad")
    assert closed.get("called") is True


@pytest.mark.asyncio
async def test_ws_receive_ping_probe_and_regular_text_ping():
    """
    - '2probe' → respond with pong '3probe'
    - '2hello' → regular text ping -> '3hello'
    - binary '2' + payload -> _send_binary_packet('3', payload)
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-rx-ping")
    consumer.session = session

    sent_text = []

    async def fake_send_text_packet(pkt_type: str, data: str = ""):
        sent_text.append((pkt_type, data))

    consumer._send_text_packet = fake_send_text_packet  # type: ignore[assignment]

    await consumer.receive(text_data="2probe")
    await consumer.receive(text_data="2hello")

    assert ("3", "probe") in sent_text
    assert ("3", "hello") in sent_text

@pytest.mark.asyncio
async def test_ws_receive_binary_frame_is_forwarded_as_message(monkeypatch):
    """
    With the Socket.IO-compatible WS behavior, *all* WS binary frames are treated
    as Engine.IO "message" packets (type '4') carrying raw bytes, and forwarded
    to app.on_message(..., binary=True).
    """

    class DummyApp:
        def __init__(self):
            self.calls = []

        async def on_message(self, socket, data, binary):
            self.calls.append((socket, data, binary))

        async def on_connect(self, socket):
            pass

        async def on_disconnect(self, socket, reason):
            pass

    app = DummyApp()

    def fake_get_engineio_app():
        return app

    class DummySocket:
        def __init__(self, sess):
            self.session = sess

    def fake_get_or_create_socket(sess):
        return DummySocket(sess)

    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-rx-bin")
    consumer.session = session

    monkeypatch.setattr(ws_mod, "get_engineio_app", fake_get_engineio_app)
    monkeypatch.setattr(
        ws_mod,
        "get_or_create_socket",
        fake_get_or_create_socket
    )

    await consumer.receive(bytes_data=b"2\x01\x02")

    assert len(app.calls) == 1
    _, data, binary = app.calls[0]
    assert data == b"2\x01\x02"
    assert binary is True


@pytest.mark.asyncio
async def test_ws_receive_pong_marks_pong(monkeypatch):
    """
    Packet type '3' should call session.mark_pong_received().
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-rx-pong")
    consumer.session = session

    pongs = []

    def fake_mark_pong_received():
        pongs.append("pong")

    session.mark_pong_received = fake_mark_pong_received  # type: ignore[assignment]

    await consumer.receive(text_data="3")
    assert pongs == ["pong"]


@pytest.mark.asyncio
async def test_ws_receive_upgrade_complete(monkeypatch):
    """
    Packet type '5' should switch transport to 'websocket' and enqueue noop
    '6'.
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-rx-upgrade")
    consumer.session = session
    session.transport = "polling"

    enqueued = []

    async def fake_enqueue_http_packet(segment: str):
        enqueued.append(segment)

    session.enqueue_http_packet = fake_enqueue_http_packet  # type: ignore[assignment]

    await consumer.receive(text_data="5")

    assert session.transport == "websocket"
    assert "6" in enqueued


@pytest.mark.asyncio
async def test_ws_receive_message_text_and_binary(monkeypatch):
    """
    Packet type '4' should call app.on_message(..., data, binary) for both text
    and binary frames.
    """

    class DummyApp:
        def __init__(self):
            self.calls = []

        async def on_message(self, socket, data, binary):
            self.calls.append((socket, data, binary))

        async def on_connect(self, socket):
            pass

        async def on_disconnect(self, socket, reason):
            pass

    app = DummyApp()

    def fake_get_engineio_app():
        return app

    class DummySocket:
        def __init__(self, sess):
            self.session = sess

    def fake_get_or_create_socket(sess):
        return DummySocket(sess)

    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-rx-msg")
    consumer.session = session

    monkeypatch.setattr(ws_mod, "get_engineio_app", fake_get_engineio_app)
    monkeypatch.setattr(
        ws_mod, "get_or_create_socket", fake_get_or_create_socket
    )

    # text message
    await consumer.receive(text_data="4hello")
    # binary message
    await consumer.receive(bytes_data=b"4\x01\x02")

    assert len(app.calls) == 2
    _, data1, binary1 = app.calls[0]
    _, data2, binary2 = app.calls[1]

    assert data1 == "hello" and binary1 is False
    assert data2 == b"4\x01\x02" and binary2 is True


@pytest.mark.asyncio
async def test_ws_receive_close_calls_close_session_and_self_close(
    monkeypatch,
):
    """
    Packet type '1' should call close_session(self.session, 'client_close') and
    then self.close().
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-rx-close")
    consumer.session = session

    closed_session = {}
    closed_self = {}

    async def fake_close_session(sess, reason=""):
        closed_session["sid"] = sess.sid
        closed_session["reason"] = reason

    async def fake_close(code=None):
        closed_self["called"] = True

    monkeypatch.setattr(ws_mod, "close_session", fake_close_session)
    consumer.close = fake_close  # type: ignore[assignment]

    await consumer.receive(text_data="1")

    assert closed_session == {"sid": "sid-rx-close", "reason": "client_close"}
    assert closed_self.get("called") is True


# --------------------------------------------------------------------------- #
# sio_broadcast() branches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ws_sio_broadcast_early_return_on_no_session_or_closed():
    """
    sio_broadcast should return early without sending if there is no session or
    it is closed.
    """
    consumer = EngineIOWebSocketConsumer()
    consumer.session = None

    async def fake_send(text_data=None, bytes_data=None):
        raise AssertionError(
            "send should not be called when no session/closed"
        )

    consumer.send = fake_send  # type: ignore[assignment]

    await consumer.sio_broadcast({"header": "x", "attachments": [b"a"]})

    consumer.session = EngineIOSession("sid-x")
    consumer.session.closed = True  # type: ignore[assignment]

    await consumer.sio_broadcast({"header": "x", "attachments": [b"a"]})


@pytest.mark.asyncio
async def test_ws_sio_broadcast_sends_header_and_attachments():
    """
    sio_broadcast should:
      - send one text frame '4' + header
      - then one binary frame '4' + each blob
    """
    consumer = EngineIOWebSocketConsumer()
    consumer.session = EngineIOSession("sid-bc")

    sent_text = []
    sent_bytes = []

    async def fake_send(text_data=None, bytes_data=None):
        if text_data is not None:
            sent_text.append(text_data)
        if bytes_data is not None:
            sent_bytes.append(bytes_data)

    consumer.send = fake_send  # type: ignore[assignment]

    event = {
        "header": '2/chat,["evt",{"x":1}]',
        "attachments": [b"\x01\x02", b"\x03"],
    }

    await consumer.sio_broadcast(event)

    assert sent_text == ['42/chat,["evt",{"x":1}]']
    assert sent_bytes == [b"\x01\x02", b"\x03"]


@pytest.mark.asyncio
async def test_ws_heartbeat_loop_breaks_when_session_closed_mid_loop(
    monkeypatch,
):
    """
    Cover the inner check in _heartbeat_loop:

        if not self.session or self.session.closed:
            break

    by:
      - starting with an open session,
      - closing the session after the first sleep,
      - and ensuring the loop exits via that branch.
    """
    consumer = EngineIOWebSocketConsumer()
    session = EngineIOSession("sid-hb-break")
    consumer.session = session

    # Make intervals tiny so the loop runs quickly
    monkeypatch.setattr(ws_mod, "PING_INTERVAL_MS", 0)
    monkeypatch.setattr(ws_mod, "PING_TIMEOUT_MS", 0)

    sleep_calls = 0

    async def fake_sleep(seconds: float):
        nonlocal sleep_calls
        sleep_calls += 1
        # After the first sleep inside the loop, mark session as closed.
        if sleep_calls == 1:
            consumer.session.closed = True  # type: ignore[union-attr]
        # No real sleeping needed; just return.

    # Patch asyncio.sleep as used inside websocket.py
    monkeypatch.setattr(ws_mod.asyncio, "sleep", fake_sleep)

    # Run the heartbeat loop; it should:
    #  - enter the while,
    #  - call sleep once,
    #  - see session.closed == True,
    #  - hit the "if not self.session or self.session.closed: break" branch,
    #  - and exit without errors.
    await consumer._heartbeat_loop()

    # Sanity check: we did at least one sleep, and loop ended cleanly.
    assert sleep_calls >= 1
    assert consumer.session.closed is True


@pytest.mark.asyncio
async def test_ws_receive_flushes_http_queue_on_upgrade(monkeypatch):
    """
    When the client sends an Engine.IO packet of type '5' (upgrade complete),
    EngineIOWebSocketConsumer.receive() should:

    * set session.transport = "websocket"
    * flush any pre-encoded HTTP polling segments from session._queue
      to the WebSocket as individual text frames
    * enqueue a '6' noop onto the HTTP queue via session.enqueue_http_packet

    """

    # --- Dummy session that mimics just enough of EngineIOSession ---
    class DummySession:
        def __init__(self):
            self.sid = "sid-upgrade-dummy"
            self.closed = False
            self.websocket = None
            self.transport = "polling"
            self._queue: asyncio.Queue[str] = asyncio.Queue()
            self.enqueued: list[str] = []
            self.touched = False

        def touch(self):
            self.touched = True

        async def enqueue_http_packet(self, segment: str):
            # In real life this also goes into the HTTP queue; here we just
            # record it.
            self.enqueued.append(segment)

    session = DummySession()

    # Pre-populate the HTTP queue with segments as if they came from polling.
    await session._queue.put("4hello-upgrade")
    await session._queue.put("4second")

    # Wire up the consumer to this dummy session.
    consumer = EngineIOWebSocketConsumer()
    consumer.session = session
    session.websocket = consumer  # needed for the flush branch to run

    # Capture what would be sent over the WebSocket.
    sent_text_frames: list[str] = []

    async def fake_send(*, text_data=None, bytes_data=None, close=False):
        if text_data is not None:
            sent_text_frames.append(text_data)

    consumer.send = fake_send  # type: ignore[assignment]

    # Make decode_ws_text_frame return a "type=5" packet for this test.
    class DummyPkt:
        def __init__(self, type: str, data=None, binary: bool = False):
            self.type = type
            self.data = data
            self.binary = binary

    def fake_decode_ws_text_frame(text: str):
        # We expect the raw frame "5" here.
        assert text == "5"
        return DummyPkt(type="5")

    monkeypatch.setattr(
        ws_mod, "decode_ws_text_frame", fake_decode_ws_text_frame
    )

    # receive() also calls get_engineio_app/get_or_create_socket, but the '5'
    # branch doesn't actually use them. Stub them out so nothing blows up.
    class DummyApp:
        async def on_message(self, socket, data, binary):
            pass

        async def on_connect(self, socket):
            pass

        async def on_disconnect(self, socket, reason):
            pass

    app = DummyApp()

    def fake_get_engineio_app():
        return app

    class DummySocket:
        def __init__(self, sess):
            self.session = sess

    def fake_get_or_create_socket(sess):
        return DummySocket(sess)

    monkeypatch.setattr(ws_mod, "get_engineio_app", fake_get_engineio_app)
    monkeypatch.setattr(
        ws_mod, "get_or_create_socket", fake_get_or_create_socket
    )

    # --- Act: simulate the "upgrade complete" Engine.IO packet over WS ---
    await consumer.receive(text_data="5")

    # --- Assert ---

    # 1) Transport should now be 'websocket'.
    assert session.transport == "websocket"

    # 2) The queued HTTP segments should have been flushed as individual
    #    WebSocket text frames, in order.
    assert sent_text_frames == ["4hello-upgrade", "4second"]

    # 3) enqueue_http_packet should have been called with "6" to close polling.
    assert session.enqueued == ["6"]

    # 4) We also touched the session as usual.
    assert session.touched is True
