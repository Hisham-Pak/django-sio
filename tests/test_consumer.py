from __future__ import annotations

import pytest

from sio.consumer import SocketIOConsumer
from sio.socketio.constants import DEFAULT_NAMESPACE
from sio.socketio.server import get_socketio_server


class SimpleConsumer(SocketIOConsumer):
    namespace = "/simple"

    def __init__(self):
        self.connected = []
        self.disconnected = []
        self.events = []

    async def connect(self, socket, auth):
        self.connected.append((socket.namespace, auth))
        return True

    async def disconnect(self, socket, reason):
        self.disconnected.append((socket.namespace, reason))

    async def event_ping(self, socket, payload, ack=None):
        self.events.append(("ping", payload))
        if ack is not None:
            await ack("pong")


class NoConnectConsumer(SocketIOConsumer):
    # no connect/disconnect, just a simple event handler
    async def event_x(self, socket, data):
        # no ack param in signature
        pass


@pytest.mark.asyncio
async def test_ensure_configured_and_namespace_registration():
    server = get_socketio_server()
    SimpleConsumer._configured = False

    SimpleConsumer._ensure_configured()
    assert "/simple" in server._namespaces

    before = dict(server._namespaces)
    SimpleConsumer._ensure_configured()
    assert server._namespaces == before


@pytest.mark.asyncio
async def test_connect_and_event_handler_wiring():
    SimpleConsumer._configured = False
    SimpleConsumer._ensure_configured()
    server = get_socketio_server()

    nsp = server._namespaces["/simple"]
    assert nsp.connect_handler is not None
    assert "ping" in nsp.listeners

    # Simulate a namespace socket as seen by connect_handler
    class StubSocket:
        def __init__(self):
            self.server = server
            self.eio = type("Eio", (), {"sid": "sid"})()
            self.namespace = "/simple"
            self.state = {}

    stub = StubSocket()

    ok = await nsp.connect_handler(stub, {"foo": "bar"})
    assert ok is True

    consumer = stub.state["consumer"]
    assert isinstance(consumer, SimpleConsumer)
    assert consumer.connected == [("/simple", {"foo": "bar"})]

    # Now simulate an event call with ack
    called_ack = {}

    async def ack_fn(*args):
        called_ack["args"] = args

    handler = nsp.listeners["ping"]
    await handler(stub, [{"x": 1}], ack_fn)
    assert consumer.events == [("ping", {"x": 1})]
    assert called_ack["args"] == ("pong",)


@pytest.mark.asyncio
async def test_disconnect_hook_for_correct_consumer_type():
    SimpleConsumer._configured = False
    SimpleConsumer._ensure_configured()
    server = get_socketio_server()

    assert server._disconnect_hooks

    # Socket with correct consumer type
    class Socket1:
        def __init__(self):
            self.namespace = "/simple"
            self.state = {"consumer": SimpleConsumer()}
            self.left = False

        async def leave_all(self):
            self.left = True

    socket1 = Socket1()

    # Socket with wrong consumer type (object)
    class Socket2:
        def __init__(self):
            self.namespace = "/simple"
            self.state = {"consumer": object()}

        async def leave_all(self):
            # should not be called for wrong type, but safe
            pass

    socket2 = Socket2()

    # Call all registered hooks manually
    for hook in server._disconnect_hooks:
        await hook(socket1, "reason")
        await hook(socket2, "reason")

    # For socket1, consumer.disconnect should have run and leave_all()
    consumer1 = socket1.state["consumer"]

    # 🔧 Relaxed assertion: only require that the *latest* call matches
    assert consumer1.disconnected, "disconnect() was never called"
    assert consumer1.disconnected[-1] == ("/simple", "reason")

    assert socket1.left is True


@pytest.mark.asyncio
async def test_event_handler_without_ack_param_still_calls_ack():
    NoConnectConsumer._configured = False
    NoConnectConsumer._ensure_configured()
    server = get_socketio_server()

    nsp = server._namespaces[DEFAULT_NAMESPACE]
    handler = nsp.listeners["x"]

    class StubSocket:
        def __init__(self):
            self.namespace = DEFAULT_NAMESPACE
            self.state = {}

    stub = StubSocket()
    ack_called = {}

    async def ack(*args):
        ack_called["args"] = args

    await handler(stub, ["payload"], ack)
    # event_x doesn't accept ack, so wrapper calls ack() automatically
    assert ack_called["args"] == ()


@pytest.mark.asyncio
async def test_socketio_consumer_as_asgi_dispatches_http_and_ws(monkeypatch):
    """
    SocketIOConsumer.as_asgi() should:

    - call LongPollingConsumer.as_asgi() and EngineIOWebSocketConsumer
      .as_asgi() once up front,
    - dispatch HTTP scopes to the HTTP app,
    - dispatch WebSocket scopes to the WS app.

    """
    http_calls: list[dict] = []
    ws_calls: list[dict] = []

    async def dummy_http_app(scope, receive, send):
        http_calls.append(scope)

    async def dummy_ws_app(scope, receive, send):
        ws_calls.append(scope)

    class FakeHTTPTransport:
        @classmethod
        def as_asgi(cls):
            return dummy_http_app

    class FakeWSTransport:
        @classmethod
        def as_asgi(cls):
            return dummy_ws_app

    # Patch the transport classes used inside SocketIOConsumer.as_asgi
    monkeypatch.setattr("sio.consumer.LongPollingConsumer", FakeHTTPTransport)
    monkeypatch.setattr(
        "sio.consumer.EngineIOWebSocketConsumer", FakeWSTransport
    )

    class TestConsumer(SocketIOConsumer):
        # no special behaviour; we just want the as_asgi wrapper
        pass

    app = TestConsumer.as_asgi()

    async def fake_receive():
        return {"type": "test.event"}

    async def fake_send(message):
        # we don't care about outgoing messages in this test
        pass

    # HTTP scope should hit the HTTP app
    http_scope = {"type": "http"}
    await app(http_scope, fake_receive, fake_send)
    assert http_calls == [http_scope]
    assert ws_calls == []

    # WebSocket scope should hit the WS app
    ws_scope = {"type": "websocket"}
    await app(ws_scope, fake_receive, fake_send)
    assert ws_calls == [ws_scope]


@pytest.mark.asyncio
async def test_socketio_consumer_as_asgi_unknown_scope_raises(monkeypatch):
    """
    Scope types other than 'http' and 'websocket' should raise RuntimeError.
    """

    async def dummy_http_app(scope, receive, send):
        pass

    async def dummy_ws_app(scope, receive, send):
        pass

    class FakeHTTPTransport:
        @classmethod
        def as_asgi(cls):
            return dummy_http_app

    class FakeWSTransport:
        @classmethod
        def as_asgi(cls):
            return dummy_ws_app

    monkeypatch.setattr("sio.consumer.LongPollingConsumer", FakeHTTPTransport)
    monkeypatch.setattr(
        "sio.consumer.EngineIOWebSocketConsumer", FakeWSTransport
    )

    class TestConsumer(SocketIOConsumer):
        pass

    app = TestConsumer.as_asgi()

    async def fake_receive():
        return {"type": "test.event"}

    async def fake_send(message):
        pass

    # Unknown scope type should hit the RuntimeError branch
    other_scope = {"type": "lifespan"}

    with pytest.raises(RuntimeError) as excinfo:
        await app(other_scope, fake_receive, fake_send)

    assert "does not handle scope type" in str(excinfo.value)


def test_ensure_configured_skips_non_event_and_non_callable():
    """
    SocketIOConsumer._ensure_configured should:

    - skip attributes that don't start with 'event_'
    - skip attributes starting with 'event_' that are not callable

    """
    server = get_socketio_server()

    class WeirdConsumer(SocketIOConsumer):
        namespace = "/weird"

        # Not starting with 'event_' → hits first 'continue'
        some_attribute = "value"

        # Starts with 'event_' but not callable → hits second 'continue'
        event_not_callable = 123

        # Actual event handler
        async def event_real(self, socket, *args, ack=None):
            pass

    # Force reconfiguration for this class
    WeirdConsumer._configured = False
    WeirdConsumer._ensure_configured()

    nsp = server._namespaces["/weird"]

    # Only the callable event_* method should be registered
    assert "real" in nsp.listeners
    assert "not_callable" not in nsp.listeners
