from __future__ import annotations

import asyncio
import time
import pytest

from sio.engineio.constants import ENGINE_IO_VERSION, TRANSPORT_POLLING
from sio.engineio.packets import Packet, encode_text_packet
from sio.engineio.polling import LONG_POLL_TIMEOUT_S, LongPollingConsumer
from sio.engineio.session import EngineIOSession, create_session


@pytest.mark.asyncio
async def test_polling_invalid_query_parameters():
    """
    If EIO or transport query params are invalid, handle() should respond 400
    with a clear error message.
    """
    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        # Wrong EIO version
        "query_string": b"EIO=3&transport=polling",
    }

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    assert captured["status"] == 400
    assert b"Invalid Engine.IO query parameters" in captured["body"]


@pytest.mark.asyncio
async def test_polling_concurrent_get_closes_session_and_returns_400(
    monkeypatch,
):
    """
    If a second GET arrives while active_get is True, the session should be
    closed with reason 'concurrent_get' and client gets 400.
    """
    from sio.engineio import polling as polling_mod

    session = await create_session()
    session.active_get = True

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    captured = {}
    closed = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    async def fake_close_session(sess, reason=""):
        closed["sid"] = sess.sid
        closed["reason"] = reason

    consumer.send_response = fake_send_response  # type: ignore[assignment]
    monkeypatch.setattr(polling_mod, "close_session", fake_close_session)

    await consumer._handle_get(session)

    assert captured["status"] == 400
    assert b"Multiple concurrent GET not allowed" in captured["body"]
    assert closed == {"sid": session.sid, "reason": "concurrent_get"}


@pytest.mark.asyncio
async def test_polling_concurrent_post_closes_session_and_returns_400(
    monkeypatch,
):
    """
    If a second POST arrives while active_post is True, the session should be
    closed with reason 'concurrent_post' and client gets 400.
    """
    from sio.engineio import polling as polling_mod

    session = await create_session()
    session.active_post = True

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "POST",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    captured = {}
    closed = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    async def fake_close_session(sess, reason=""):
        closed["sid"] = sess.sid
        closed["reason"] = reason

    consumer.send_response = fake_send_response  # type: ignore[assignment]
    monkeypatch.setattr(polling_mod, "close_session", fake_close_session)

    await consumer._handle_post(session, b"4test")

    assert captured["status"] == 400
    assert b"Multiple concurrent POST not allowed" in captured["body"]
    assert closed == {"sid": session.sid, "reason": "concurrent_post"}


@pytest.mark.asyncio
async def test_polling_post_bad_payload_returns_400(monkeypatch):
    """
    If decode_http_payload raises ValueError, POST should respond with 400 'Bad
    payload: ...'.
    """
    from sio.engineio import polling as polling_mod

    session = await create_session()

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "POST",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    # IMPORTANT: sync function, not async
    def fake_decode_http_payload(body: bytes):
        raise ValueError("broken")

    consumer.send_response = fake_send_response  # type: ignore[assignment]
    monkeypatch.setattr(
        polling_mod, "decode_http_payload", fake_decode_http_payload
    )

    await consumer._handle_post(session, b"something")

    assert captured["status"] == 400
    assert b"Bad payload: broken" in captured["body"]


@pytest.mark.asyncio
async def test_polling_handle_405_for_unknown_method(monkeypatch):
    """
    When method is neither GET nor POST, but sid and session exist, handle()
    should return 405 Method not allowed.
    """

    # Create a real session so get_session(sid) works.
    session = await create_session()

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "PUT",  # unsupported
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"ignored")

    assert captured["status"] == 405
    assert b"Method not allowed" in captured["body"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class DummyApp:
    def __init__(self):
        self.connected = []
        self.messages = []
        self.disconnected = []

    async def on_connect(self, socket):
        self.connected.append(socket)

    async def on_message(self, socket, data, binary):
        self.messages.append((socket, data, binary))

    async def on_disconnect(self, socket, reason):
        self.disconnected.append((socket, reason))


class DummySocket:
    def __init__(self, session):
        self._session = session


# --------------------------------------------------------------------------- #
# handle() top-level branches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_polling_handle_handshake_triggers_on_connect(monkeypatch):
    """
    GET with no sid should perform Engine.IO handshake and call app.on_connect.
    """
    from sio.engineio import polling as polling_mod

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}".encode(  # noqa: E501
            "ascii"
        ),
    }

    app = DummyApp()
    session = EngineIOSession("sid123")
    dummy_socket = DummySocket(session)

    async def fake_create_session():
        return session

    def fake_get_engineio_app():
        return app

    def fake_get_or_create_socket(sess):
        assert sess is session
        return dummy_socket

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    monkeypatch.setattr(polling_mod, "create_session", fake_create_session)
    monkeypatch.setattr(polling_mod, "get_engineio_app", fake_get_engineio_app)
    monkeypatch.setattr(
        polling_mod, "get_or_create_socket", fake_get_or_create_socket
    )
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    # Handshake returns open packet (type 0) as plain text
    assert captured["status"] == 200
    assert captured["body"].decode("utf-8").startswith("0")
    # Application on_connect was called
    assert app.connected and app.connected[0] is dummy_socket


@pytest.mark.asyncio
async def test_polling_handle_missing_sid_for_post(monkeypatch):
    """
    POST with no sid should return 400 'Missing sid'.
    """
    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "POST",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}".encode(  # noqa: E501
            "ascii"
        ),
    }

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]
    await consumer.handle(b"whatever")

    assert captured["status"] == 400
    assert b"Missing sid" in captured["body"]


@pytest.mark.asyncio
async def test_polling_handle_unknown_sid(monkeypatch):
    """
    If get_session returns None, handle() should respond 400 with 'Unknown or
    expired sid'.
    """
    from sio.engineio import polling as polling_mod

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid=abc".encode(  # noqa: E501
            "ascii"
        ),
    }

    async def fake_get_session(sid):
        assert sid == "abc"
        return None

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    assert captured["status"] == 400
    assert b"Unknown or expired sid" in captured["body"]


@pytest.mark.asyncio
async def test_polling_handle_session_timed_out(monkeypatch):
    """
    If session.is_timed_out() is True, handle() should
    close_session(reason='timeout') and respond 400 'Unknown or expired sid'.
    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid1"
            self.closed = False
            self.transport = TRANSPORT_POLLING

        def is_timed_out(self):
            return True

    session = Sess()

    async def fake_get_session(sid):
        return session

    closed = {}

    async def fake_close_session(sess, reason=""):
        closed["sid"] = sess.sid
        closed["reason"] = reason

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    monkeypatch.setattr(polling_mod, "close_session", fake_close_session)
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    assert closed == {"sid": "sid1", "reason": "timeout"}
    assert captured["status"] == 400
    assert b"Unknown or expired sid" in captured["body"]


@pytest.mark.asyncio
async def test_polling_handle_closed_session(monkeypatch):
    """
    If session.closed is True (but not timed out), handle() should respond 400
    'Unknown or expired sid'.
    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid2"
            self.closed = True
            self.transport = TRANSPORT_POLLING

        def is_timed_out(self):
            return False

    session = Sess()

    async def fake_get_session(sid):
        return session

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    assert captured["status"] == 400
    assert b"Unknown or expired sid" in captured["body"]


@pytest.mark.asyncio
async def test_polling_handle_session_upgraded_to_websocket(monkeypatch):
    """
    If session.transport == 'websocket', polling transport is closed and
    handle() should reply 400 'Polling transport closed (upgraded to
    WebSocket)'.
    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid3"
            self.closed = False
            self.transport = "websocket"

        def is_timed_out(self):
            return False

    session = Sess()

    async def fake_get_session(sid):
        return session

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    assert captured["status"] == 400
    assert (
        b"Polling transport closed (upgraded to WebSocket)" in captured["body"]
    )


# --------------------------------------------------------------------------- #
# _handle_get branches (ping vs no ping, non-empty vs empty payload)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_handle_get_sends_ping_and_body(monkeypatch):
    """
    _handle_get should:

    - set active_get True during processing,
    - trigger server-initiated ping when should_send_ping() is True,
    - call http_next_payload() and return its body.
    """
    consumer = LongPollingConsumer()

    class Sess:
        def __init__(self):
            self.sid = "sid-get"
            self.active_get = False
            self.closed = False
            self.transport = TRANSPORT_POLLING
            self.enqueued = []
            self.mark_ping_called = False

        def should_send_ping(self):
            return True

        async def enqueue_http_packet(self, segment: str):
            self.enqueued.append(segment)

        def mark_ping_sent(self):
            self.mark_ping_called = True

        async def http_next_payload(self, timeout: float) -> bytes:
            # For this test, return a non-empty payload
            assert timeout == LONG_POLL_TIMEOUT_S
            return b"payload"

    session = Sess()

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]

    assert session.active_get is False
    await consumer._handle_get(session)
    # active_get reset by finally
    assert session.active_get is False
    # ping enqueued (type "2")
    assert "2" in session.enqueued
    assert session.mark_ping_called is True
    # response body is whatever http_next_payload returned
    assert captured["status"] == 200
    assert captured["body"] == b"payload"


@pytest.mark.asyncio
async def test_handle_get_without_ping_and_empty_payload():
    """
    When should_send_ping() is False, no ping is enqueued and empty payload is
    allowed.
    """
    consumer = LongPollingConsumer()

    class Sess:
        def __init__(self):
            self.sid = "sid-get"
            self.active_get = False
            self.closed = False
            self.transport = TRANSPORT_POLLING
            self.enqueued = []
            self.mark_ping_called = False

        def should_send_ping(self):
            return False

        async def enqueue_http_packet(self, segment: str):
            self.enqueued.append(segment)

        def mark_ping_sent(self):
            raise AssertionError("should not be called")

        async def http_next_payload(self, timeout: float) -> bytes:
            return b""

    session = Sess()

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer._handle_get(session)

    assert session.enqueued == []
    assert captured["status"] == 200
    assert captured["body"] == b""


@pytest.mark.asyncio
async def test_handle_get_delayed_ping_task_executes(monkeypatch):
    """
    Cover the delayed_ping() inner coroutine in _handle_get():

    - should_send_ping() is False so it schedules delayed_ping()
    - PING_INTERVAL_MS is patched very small so the delay is short
    - http_next_payload() awaits long enough for delayed_ping() to run
    - delayed_ping() enqueues a ping ("2") and calls mark_ping_sent()
    """
    from sio.engineio import polling as polling_mod

    # Make the delayed ping happen quickly.
    monkeypatch.setattr(polling_mod, "PING_INTERVAL_MS", 5)  # 5ms

    consumer = LongPollingConsumer()

    class Sess:
        def __init__(self):
            self.sid = "sid-delayed-ping"
            self.active_get = False
            self.closed = False
            self.transport = TRANSPORT_POLLING
            self.enqueued = []
            self.mark_ping_called = False
            # Ensure remaining_ms > 0 (so delayed ping is scheduled, not immediate).
            self.last_ping_sent = time.time()

        def should_send_ping(self):
            return False

        async def enqueue_http_packet(self, segment: str):
            self.enqueued.append(segment)

        def mark_ping_sent(self):
            self.mark_ping_called = True

        async def http_next_payload(self, timeout: float) -> bytes:
            # Wait longer than the patched interval so delayed_ping() fires first.
            await asyncio.sleep(0.02)
            return b"payload-after-delayed-ping"

    session = Sess()

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer._handle_get(session)

    # delayed_ping() should have executed
    assert session.mark_ping_called is True
    assert "2" in session.enqueued

    # normal response still returned
    assert captured["status"] == 200
    assert captured["body"] == b"payload-after-delayed-ping"


@pytest.mark.asyncio
async def test_handle_get_delayed_ping_skips_when_inactive(monkeypatch):
    """
    Cover the delayed_ping() early-return branch:

        if session.closed or not session.active_get: ... return

    We force delayed_ping to be scheduled, then flip active_get False before it
    executes.
    """
    from sio.engineio import polling as polling_mod

    # Make delayed ping happen quickly.
    monkeypatch.setattr(polling_mod, "PING_INTERVAL_MS", 10)  # 10ms

    consumer = LongPollingConsumer()

    class Sess:
        def __init__(self):
            self.sid = "sid-delayed-ping-skip"
            self.active_get = False
            self.closed = False
            self.transport = TRANSPORT_POLLING
            self.enqueued = []
            self.mark_ping_called = False
            # Ensure remaining_ms > 0 so delayed ping is scheduled.
            self.last_ping_sent = time.time()

        def should_send_ping(self):
            return False

        async def enqueue_http_packet(self, segment: str):
            self.enqueued.append(segment)

        def mark_ping_sent(self):
            self.mark_ping_called = True

        async def http_next_payload(self, timeout: float) -> bytes:
            # Start a background task that turns active_get off before
            # delayed_ping runs.
            async def flip_inactive():
                await asyncio.sleep(0.001)  # 1ms < 10ms interval
                self.active_get = False

            asyncio.create_task(flip_inactive())

            # Wait long enough for delayed_ping to attempt to run (and skip),
            # then return payload so _handle_get completes.
            await asyncio.sleep(0.03)
            return b"payload"

    session = Sess()

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer._handle_get(session)

    # delayed_ping should have skipped, so no ping enqueued / marked
    assert session.enqueued == []
    assert session.mark_ping_called is False

    # still returns a normal response
    assert captured["status"] == 200
    assert captured["body"] == b"payload"


# --------------------------------------------------------------------------- #
# _handle_post and _handle_packet_from_http branches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_handle_post_success_and_packet_handling(monkeypatch):
    """
    _handle_post should:

    - set active_post True during processing,
    - decode payload into Packet list,
    - for each packet type:
        * '3' -> mark_pong_received()
        * '4' -> app.on_message()
        * '1' -> close_session(reason='client_close')
        * '2' -> enqueue_http_packet('3'+data)
      and ignore others,
    - send 200 'ok' on success,
    - reset active_post to False.
    """
    from sio.engineio import polling as polling_mod

    consumer = LongPollingConsumer()
    app = DummyApp()
    session = EngineIOSession("sidX")

    # monkeypatch get_engineio_app + get_or_create_socket
    def fake_get_engineio_app():
        return app

    socket_obj = DummySocket(session)

    def fake_get_or_create_socket(sess):
        assert sess is session
        return socket_obj

    monkeypatch.setattr(polling_mod, "get_engineio_app", fake_get_engineio_app)
    monkeypatch.setattr(
        polling_mod, "get_or_create_socket", fake_get_or_create_socket
    )

    # track close_session
    closed = {}

    async def fake_close_session(sess, reason=""):
        closed["sid"] = sess.sid
        closed["reason"] = reason

    monkeypatch.setattr(polling_mod, "close_session", fake_close_session)

    # Packet list to exercise all branches
    packets = [
        Packet(type="3", data="", binary=False),  # pong
        Packet(type="4", data="hi", binary=False),  # message (text)
        Packet(type="1", data="", binary=False),  # close
        Packet(type="2", data="data", binary=False),  # ping
        Packet(type="6", data="", binary=False),  # noop (ignored)
    ]

    def fake_decode_http_payload(body: bytes):
        assert body == b"body"
        return packets

    monkeypatch.setattr(
        polling_mod, "decode_http_payload", fake_decode_http_payload
    )

    enqueued = []

    async def fake_enqueue_http_packet(segment: str):
        enqueued.append(segment)

    session.enqueue_http_packet = fake_enqueue_http_packet  # type: ignore[assignment]

    # track pong
    pongs = []

    def fake_mark_pong_received():
        pongs.append("pong")

    session.mark_pong_received = fake_mark_pong_received  # type: ignore[assignment]

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer.send_response = fake_send_response  # type: ignore[assignment]

    assert session.active_post is False
    await consumer._handle_post(session, b"body")
    # active_post reset
    assert session.active_post is False

    # pong branch hit
    assert pongs == ["pong"]
    # message branch hit
    assert app.messages == [(socket_obj, "hi", False)]
    # close branch hit
    assert closed == {"sid": "sidX", "reason": "client_close"}
    # ping branch enqueued a '3<data>' packet
    assert encode_text_packet("3", "data") in enqueued
    # noop packet ignored (no extra side effects beyond above)
    assert captured["status"] == 200
    assert captured["body"] == b"ok"


@pytest.mark.asyncio
async def test_longpolling_disconnect_is_noop():
    """
    LongPollingConsumer.disconnect() is a no-op, but we call it to cover the
    method.
    """
    consumer = LongPollingConsumer()
    await consumer.disconnect()


@pytest.mark.asyncio
async def test_handle_get_dispatch_and_concurrent_get_branch(monkeypatch):
    """
    Handle() should:

    - call session.touch()
    - dispatch GET to _handle_get()
    - and inside _handle_get, when session.active_get is True,
      trigger the concurrent_get close + 400 response branch.

    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid-cg"
            self.transport = TRANSPORT_POLLING
            self.closed = False
            self.active_get = True  # triggers concurrent_get branch
            self.touched = False

        def is_timed_out(self) -> bool:
            return False

        def touch(self) -> None:
            self.touched = True

    session = Sess()

    async def fake_get_session(sid: str):
        assert sid == session.sid
        return session

    closed = {}

    async def fake_close_session(sess, reason=""):
        closed["sid"] = sess.sid
        closed["reason"] = reason

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "GET",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    monkeypatch.setattr(polling_mod, "close_session", fake_close_session)
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    # session.touch() must have been called before _handle_get
    assert session.touched is True

    # concurrent_get branch in _handle_get
    assert captured["status"] == 400
    assert b"Multiple concurrent GET not allowed" in captured["body"]
    assert closed == {"sid": session.sid, "reason": "concurrent_get"}


@pytest.mark.asyncio
async def test_handle_post_dispatches_to_handle_post(monkeypatch):
    """
    Handle() should:

    - call session.touch()
    - dispatch POST to _handle_post(session, body)

    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid-post"
            self.transport = TRANSPORT_POLLING
            self.closed = False
            self.active_post = False
            self.touched = False

        def is_timed_out(self) -> bool:
            return False

        def touch(self) -> None:
            self.touched = True

    session = Sess()

    async def fake_get_session(sid: str):
        assert sid == session.sid
        return session

    called = []

    async def fake_handle_post(self, sess, body):
        called.append((sess, body))

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "POST",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    # patch the method on the class, so the branch
    # 'await self._handle_post(...)' is hit
    monkeypatch.setattr(
        LongPollingConsumer,
        "_handle_post",
        fake_handle_post,  # type: ignore[arg-type]
    )

    # we don't expect handle() itself to send a response in this test since
    # fake_handle_post doesn't call send_response
    consumer.send_response = lambda *a, **k: None  # type: ignore[assignment]

    body = b"post-body"
    await consumer.handle(body)

    assert session.touched is True
    assert called == [(session, body)]


@pytest.mark.asyncio
async def test_handle_method_not_allowed_branch(monkeypatch):
    """
    For a known session but an unsupported HTTP method, handle() should hit the
    405 'Method not allowed' branch.
    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid-405"
            self.transport = TRANSPORT_POLLING
            self.closed = False
            self.touched = False

        def is_timed_out(self) -> bool:
            return False

        def touch(self) -> None:
            self.touched = True

    session = Sess()

    async def fake_get_session(sid: str):
        return session

    captured = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "PUT",  # unsupported
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"")

    # still touches session
    assert session.touched is True

    # and hits the 405 branch
    assert captured["status"] == 405
    assert b"Method not allowed" in captured["body"]


@pytest.mark.asyncio
async def test_handle_post_concurrent_post_branch(monkeypatch):
    """
    When session.active_post is True, _handle_post should:

    - call close_session(session, reason='concurrent_post')
    - send a 400 'Multiple concurrent POST not allowed' response
    - and return early.

    We hit this via handle() so the method-dispatch block is also covered.

    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid-concurrent-post"
            self.transport = TRANSPORT_POLLING
            self.closed = False
            self.active_post = True  # triggers the concurrent_post branch
            self.touched = False

        def is_timed_out(self) -> bool:
            return False

        def touch(self) -> None:
            self.touched = True

    session = Sess()

    async def fake_get_session(sid: str):
        assert sid == session.sid
        return session

    closed: dict[str, str] = {}

    async def fake_close_session(sess, reason: str = ""):
        closed["sid"] = sess.sid
        closed["reason"] = reason

    captured: dict[str, object] = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "POST",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    monkeypatch.setattr(polling_mod, "close_session", fake_close_session)
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"ignored-body")

    # session.touch() must have been called before _handle_post
    assert session.touched is True

    # concurrent_post branch in _handle_post
    assert captured["status"] == 400
    assert b"Multiple concurrent POST not allowed" in captured["body"]
    assert closed == {"sid": session.sid, "reason": "concurrent_post"}


@pytest.mark.asyncio
async def test_handle_post_bad_payload_valueerror_branch(monkeypatch):
    """
    When decode_http_payload raises ValueError, _handle_post should:

    - send a 400 'Bad payload: ...' response
    - return early
    - and the outer try/finally should still reset session.active_post to False

    Again we hit this via handle().

    """
    from sio.engineio import polling as polling_mod

    class Sess:
        def __init__(self):
            self.sid = "sid-bad-payload"
            self.transport = TRANSPORT_POLLING
            self.closed = False
            self.active_post = False
            self.touched = False

        def is_timed_out(self) -> bool:
            return False

        def touch(self) -> None:
            self.touched = True

    session = Sess()

    async def fake_get_session(sid: str):
        assert sid == session.sid
        return session

    # IMPORTANT: sync function, because decode_http_payload is called
    # synchronously
    def fake_decode_http_payload(body: bytes):
        assert body == b"bad-body"
        raise ValueError("boom!")

    captured: dict[str, object] = {}

    async def fake_send_response(status, body, headers=None):
        captured["status"] = status
        captured["body"] = body
        captured["headers"] = headers

    consumer = LongPollingConsumer()
    consumer.scope = {
        "type": "http",
        "method": "POST",
        "query_string": f"EIO={ENGINE_IO_VERSION}&transport={TRANSPORT_POLLING}&sid={session.sid}".encode(  # noqa: E501
            "ascii"
        ),
    }

    monkeypatch.setattr(polling_mod, "get_session", fake_get_session)
    monkeypatch.setattr(
        polling_mod, "decode_http_payload", fake_decode_http_payload
    )
    consumer.send_response = fake_send_response  # type: ignore[assignment]

    await consumer.handle(b"bad-body")

    # session.touch() must have been called
    assert session.touched is True

    # bad-payload branch hit
    assert captured["status"] == 400
    assert b"Bad payload: boom!" in captured["body"]

    # active_post should have been set to True then reset to False by finally
    assert session.active_post is False
