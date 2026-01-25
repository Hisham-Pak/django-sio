from __future__ import annotations

import pytest

from sio.engineio.app import EngineIOSocket
from sio.engineio.session import EngineIOSession
from sio.socketio.constants import DEFAULT_NAMESPACE, SIO_CONNECT, SIO_EVENT
from sio.socketio.protocol import SocketIOPacket
from sio.socketio.server import SocketIOServer, get_socketio_server

from .helpers import live_client


def test_group_name_sanitization_and_truncation():
    server = SocketIOServer()
    long_ns = "/weird/namespace! with spaces"
    long_room = "room:" + "x" * 200

    group = server._group_name(long_ns, long_room)
    assert " " not in group
    assert "!" not in group
    assert len(group) <= 99


def test_of_creates_and_reuses_namespaces():
    server = SocketIOServer()
    default_ns = server.of(DEFAULT_NAMESPACE)
    same = server.of("/")
    assert default_ns is same

    chat = server.of("/chat")
    assert chat.name == "/chat"
    assert server.of("/chat") is chat


@pytest.mark.asyncio
async def test_emit_local_vs_room_and_no_channel_layer(monkeypatch):
    server = SocketIOServer()

    class DummySession:
        def __init__(self):
            self.transport = "polling"
            self.websocket = None

    class DummyEio:
        def __init__(self):
            self._session = DummySession()

    class DummySocket:
        def __init__(self):
            self.server = server
            self.eio = DummyEio()
            self.namespace = "/nsp"
            self.rooms = {"room1"}
            self.calls = []
            self.id = "dummy-socket"

        async def emit(self, event, *args):
            self.calls.append((event, args))

    sock = DummySocket()
    server._sockets[("sid1", "/nsp")] = sock

    # Local broadcast (room=None): should call emit on all sockets in namespace
    await server.emit("evt", 1, 2, namespace="/nsp")
    assert sock.calls == [("evt", (1, 2))]

    # Room broadcast with no channel layer: should still hit local polling
    # sockets
    monkeypatch.setattr("sio.socketio.server.get_channel_layer", lambda: None)
    sock.calls.clear()

    await server.emit("evt2", 3, room="room1", namespace="/nsp")
    assert sock.calls == [("evt2", (3,))]


@pytest.mark.asyncio
async def test_engineio_hooks_on_connect_message_disconnect():
    server = SocketIOServer()
    sess = EngineIOSession("sid")
    eio = EngineIOSocket(sess)

    # on_connect: installs parser
    await server.on_connect(eio)
    assert eio.sid in server._parsers

    # on_message with missing parser: no-op
    server._parsers.pop(eio.sid)
    await server.on_message(eio, "dummy", False)

    # Reconnect and test normal path
    await server.on_connect(eio)
    parser = server._parsers[eio.sid]

    seen = []

    def fake_feed(data, binary):
        seen.append((data, binary))
        return []

    parser.feed_eio_message = fake_feed  # type: ignore[assignment]

    await server.on_message(eio, "x", False)
    assert seen == [("x", False)]

    # on_disconnect should call _on_client_disconnect for all namespace sockets
    class NS:
        def __init__(self, eio):
            self.eio = eio
            self.namespace = "/"
            self.left = False
            self.id = "ns-socket"

        async def leave_all(self):
            self.left = True

    ns_socket = NS(eio)
    server._sockets[(eio.sid, "/")] = ns_socket

    hooks_called = []

    async def hook(socket, reason):
        hooks_called.append((socket, reason))

    server.register_disconnect_hook(hook)

    await server.on_disconnect(eio, "bye")

    assert eio.sid not in server._parsers
    assert ns_socket.left is True
    assert hooks_called  # at least one hook was called


@pytest.mark.asyncio
async def test_create_namespace_socket_and_connect_handler_branches():
    server = SocketIOServer()
    nsp = server.of("/auth")

    calls = []

    @nsp.on_connect
    async def connect_handler(sock, auth):
        calls.append(("connect", auth))
        return auth.get("ok", False)

    sess = EngineIOSession("sid")
    eio = EngineIOSocket(sess)

    # Rejected connect (ok=False) → CONNECT_ERROR
    pkt = SocketIOPacket(
        type=SIO_CONNECT, namespace="/auth", data={"ok": False}
    )

    sent = []

    async def fake_send_text(payload: str):
        sent.append(payload)

    eio._send_text = fake_send_text  # type: ignore[assignment]
    await server._handle_sio_packet(eio, pkt)
    assert any(h.startswith("4/auth") for h in sent)

    # Accepted connect
    pkt2 = SocketIOPacket(
        type=SIO_CONNECT, namespace="/auth", data={"ok": True}
    )
    await server._handle_sio_packet(eio, pkt2)
    key = (eio.sid, "/auth")
    assert key in server._sockets
    ns_socket = server._sockets[key]
    assert ns_socket.namespace == "/auth"


@pytest.mark.asyncio
async def test_handle_sio_packet_missing_namespace_or_connect(monkeypatch):
    server = SocketIOServer()

    # 1) Unknown namespace + CONNECT → CONNECT_ERROR
    sess = EngineIOSession("sidX")
    eio = EngineIOSocket(sess)

    pkt_connect = SocketIOPacket(
        type=SIO_CONNECT, namespace="/unknown", data={}
    )

    sent = []

    async def fake_send_text(payload: str):
        sent.append(payload)

    eio._send_text = fake_send_text  # type: ignore[assignment]
    await server._handle_sio_packet(eio, pkt_connect)
    assert sent and sent[0].startswith("4/unknown")

    # 2) Known namespace, but no ns_socket yet + non-CONNECT → close with
    # missing_connect
    server.of("/missing")  # create namespace but don't create socket
    closed = {}

    async def fake_close(reason=""):
        closed["reason"] = reason

    eio.close = fake_close  # type: ignore[assignment]

    pkt_evt = SocketIOPacket(type=SIO_EVENT, namespace="/missing", data=None)
    await server._handle_sio_packet(eio, pkt_evt)
    assert closed["reason"] == "missing_connect"


@pytest.mark.asyncio
async def test_dispatch_event_branches():
    server = SocketIOServer()
    sock = type(
        "Sock",
        (),
        {"namespace": "/nsp"},
    )
    sock.id = "sock-dispatch"

    # no namespace configured
    await server._dispatch_event(sock, "x", [], None)

    # namespace configured but no handler
    ns = server.of("/nsp")
    await server._dispatch_event(sock, "x", [], None)

    # handler present
    called = {}

    async def handler(socket, args, ack):
        called["args"] = args
        called["ack"] = ack

    ns.listeners["x"] = handler
    await server._dispatch_event(sock, "x", [1, 2], None)
    assert called["args"] == [1, 2]


@pytest.mark.asyncio
async def test_dispatch_event_no_handler_sends_echo_ack():
    """
    Cover the branch:

        if handler is None:
            ...
            if ack_cb is not None:
                await ack_cb(*args)

    by providing an ack callback and ensuring it is called with the same args.
    """
    server = SocketIOServer()

    # Ensure the namespace exists, but do NOT register a handler for "nope".
    server.of("/nsp")

    class Sock:
        namespace = "/nsp"
        id = "sock-ack-echo"

    sock = Sock()

    ack_calls = []

    async def ack_cb(*args):
        ack_calls.append(args)

    await server._dispatch_event(sock, "nope", [1, "x", {"k": 2}], ack_cb)

    assert ack_calls == [(1, "x", {"k": 2})]


@pytest.mark.asyncio
async def test_on_client_disconnect_and_force_disconnect():
    server = SocketIOServer()

    class NS:
        def __init__(self):
            self.eio = type("Eio", (), {"sid": "sid"})()
            self.namespace = "/nsp"
            self.left = False
            self.id = "ns-1"

        async def leave_all(self):
            self.left = True

    ns_socket = NS()
    server._sockets[(ns_socket.eio.sid, ns_socket.namespace)] = ns_socket

    hooks_called = []

    async def hook(s, reason):
        hooks_called.append((s, reason))

    server.register_disconnect_hook(hook)
    await server._on_client_disconnect(ns_socket, "reason")

    assert hooks_called
    assert ns_socket.left
    assert (ns_socket.eio.sid, ns_socket.namespace) not in server._sockets

    # _force_disconnect_bad_packet → eio.close(reason)
    closed = {}

    async def fake_close(reason=""):
        closed["reason"] = reason

    ns2 = NS()
    ns2.eio.close = fake_close  # type: ignore[assignment]
    await server._force_disconnect_bad_packet(ns2, "bad")
    assert closed["reason"] == "bad"


def test_get_socketio_server_singleton():
    s1 = get_socketio_server()
    s2 = get_socketio_server()
    assert s1 is s2


@pytest.mark.asyncio
async def test_emit_room_uses_channel_layer_and_local_polling(monkeypatch):
    """
    server.emit(..., room=..., namespace=...) should:

    - call channel_layer.group_send(..., type='sio.broadcast', header,
        attachments)
    - send directly to any in-process polling sockets in that room

    """
    from sio.socketio import server as server_mod

    server = SocketIOServer()
    server.of("/roomtest")

    class FakeChannelLayer:
        def __init__(self):
            self.sent = []

        async def group_send(self, group, message):
            self.sent.append((group, message))

    layer = FakeChannelLayer()
    monkeypatch.setattr(server_mod, "get_channel_layer", lambda: layer)

    # Dummy polling socket in room 'r1'
    class DummySession:
        def __init__(self):
            self.transport = "polling"
            self.websocket = None

    class DummyEio:
        def __init__(self):
            self._session = DummySession()

    class DummySocket:
        def __init__(self):
            self.server = server
            self.eio = DummyEio()
            self.namespace = "/roomtest"
            self.rooms = {"r1"}
            self.calls = []
            self.id = "roomtest-sock"

        async def emit(self, event, *args):
            self.calls.append((event, args))

    sock = DummySocket()
    server._sockets[("sid1", "/roomtest")] = sock

    await server.emit("evt", {"x": 1}, room="r1", namespace="/roomtest")

    # channel_layer.group_send should be called
    assert layer.sent
    group, message = layer.sent[0]
    assert group.startswith("sio_")  # group name prefix
    assert message["type"] == "sio.broadcast"
    assert "header" in message
    # header should be a Socket.IO header starting with '2' (EVENT)
    assert message["header"].startswith("2")

    # Local polling socket should also have received the emit
    assert sock.calls == [("evt", ({"x": 1},))]


@pytest.mark.asyncio
async def test_engineio_websocket_sio_broadcast_sends_correct_frames():
    """
    EngineIOWebSocketConsumer.sio_broadcast should:

    - send one text frame '4' + header
    - then one binary frame '4' + each attachment

    """
    from sio.engineio.session import EngineIOSession
    from sio.engineio.websocket import EngineIOWebSocketConsumer

    consumer = EngineIOWebSocketConsumer()
    consumer.session = EngineIOSession("sid")  # not closed

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

    # one text frame '4' + header
    assert sent_text == ['42/chat,["evt",{"x":1}]']
    # two binary frames each blob
    assert sent_bytes == [b"\x01\x02", b"\x03"]


class DummyEioSocket:
    def __init__(self, sid: str):
        self.sid = sid
        self.closed_reasons: list[str] = []

    async def close(self, reason: str):
        self.closed_reasons.append(reason)


@pytest.mark.asyncio
async def test_handle_sio_packet_dispatches_to_namespace_socket():
    """
    For a non-CONNECT packet with an existing NamespaceSocket in
    server._sockets, _handle_sio_packet should call
    ns_socket._handle_packet_from_client(pkt).
    """
    server = get_socketio_server()
    nsp_name = "/ns-dispatch"
    server.of(nsp_name)  # ensure namespace exists, even if unused

    eio_socket = DummyEioSocket("eio-dispatch")

    class DummyNamespaceSocket:
        def __init__(self):
            self.calls = []
            self.eio = eio_socket
            self.namespace = nsp_name

        async def _handle_packet_from_client(self, pkt: SocketIOPacket):
            self.calls.append(pkt)

    ns_sock = DummyNamespaceSocket()
    key = (eio_socket.sid, nsp_name)

    # Preserve existing entry if any
    old = server._sockets.get(key)
    server._sockets[key] = ns_sock
    try:
        pkt = SocketIOPacket(
            type=SIO_EVENT, namespace=nsp_name, data=["ev", 1]
        )
        await server._handle_sio_packet(eio_socket, pkt)

        assert ns_sock.calls == [pkt]
    finally:
        if old is None:
            server._sockets.pop(key, None)
        else:
            server._sockets[key] = old


@pytest.mark.asyncio
async def test_on_message_processes_all_packets(monkeypatch):
    """
    SocketIOServer.on_message should:

    - call parser.feed_eio_message(data, binary),
    - iterate over all returned packets,
    - call _handle_sio_packet once per packet.

    """
    server = get_socketio_server()
    eio_socket = DummyEioSocket("eio-onmsg")

    class DummyParser:
        def __init__(self):
            self.calls = []

        def feed_eio_message(self, data, binary):
            self.calls.append((data, binary))
            return [
                SocketIOPacket(
                    type=SIO_EVENT,
                    namespace=DEFAULT_NAMESPACE,
                    data=["ev1"],
                ),
                SocketIOPacket(
                    type=SIO_EVENT,
                    namespace=DEFAULT_NAMESPACE,
                    data=["ev2"],
                ),
            ]

    parser = DummyParser()
    server._parsers[eio_socket.sid] = parser

    handled: list[tuple[DummyEioSocket, SocketIOPacket]] = []

    async def fake_handle_sio_packet(eio, pkt):
        handled.append((eio, pkt))

    orig_handle = server._handle_sio_packet
    server._handle_sio_packet = fake_handle_sio_packet  # type: ignore[assignment]
    try:
        await server.on_message(eio_socket, "payload", False)

        assert parser.calls == [("payload", False)]
        assert len(handled) == 2
        assert handled[0][1].data == ["ev1"]
        assert handled[1][1].data == ["ev2"]
    finally:
        server._handle_sio_packet = orig_handle
        server._parsers.pop(eio_socket.sid, None)


@pytest.mark.asyncio
async def test_emit_room_filters_by_namespace_room_and_transport(monkeypatch):
    """
    For room-based emit, the local fallback loop should:

      - skip sockets in other namespaces,
      - skip sockets not in the room,
      - skip sockets whose underlying transport is websocket,
      - call emit() only on sockets in the correct namespace + room
        with a non-websocket transport.

    This exercises both 'continue' branches in the emit() loop.

    """
    server = get_socketio_server()
    ns = "/emit-ns"
    room = "room1"
    server.of(ns)  # ensure namespace exists

    sends = []

    class DummySession:
        def __init__(self, transport: str):
            self.transport = transport

    class DummyEio:
        def __init__(self, transport: str):
            self._session = DummySession(transport)

    class DummySock:
        def __init__(self, nsp: str, rooms, transport: str):
            self.namespace = nsp
            self.rooms = set(rooms)
            self.eio = DummyEio(transport)
            self.id = f"{nsp}-{transport}"

        async def emit(self, event, *args):
            sends.append((self.namespace, frozenset(self.rooms), event, args))

    sock_wrong_ns = DummySock("/other", {room}, "polling")
    sock_no_room = DummySock(ns, {"other-room"}, "polling")
    sock_ws = DummySock(ns, {room}, "websocket")
    sock_ok = DummySock(ns, {room}, "polling")

    old_sockets = dict(server._sockets)
    try:
        server._sockets.clear()
        server._sockets[("e1", "/other")] = sock_wrong_ns
        server._sockets[("e2", ns)] = sock_no_room
        server._sockets[("e3", ns)] = sock_ws
        server._sockets[("e4", ns)] = sock_ok

        # Disable real channel layer and encode_packet_to_eio for this test
        monkeypatch.setattr(
            "sio.socketio.server.get_channel_layer", lambda: None
        )
        monkeypatch.setattr(
            "sio.socketio.server.encode_packet_to_eio",
            lambda pkt: ("", []),
        )

        await server.emit("event", 1, room=room, namespace=ns)

        # Only sock_ok should have received the local emit
        assert sends == [(ns, frozenset({room}), "event", (1,))]
    finally:
        server._sockets.clear()
        server._sockets.update(old_sockets)


def test_of_empty_namespace_maps_to_default():
    """
    SocketIOServer.of('') should normalise to DEFAULT_NAMESPACE and return a
    Namespace with that name (exercises 'namespace = DEFAULT_NAMESPACE').
    """
    server = get_socketio_server()
    ns = server.of("")
    assert ns.name == DEFAULT_NAMESPACE


@pytest.mark.asyncio
async def test_live_client_unsupported_transport_raises_valueerror():
    """
    live_client() should raise ValueError when an unsupported transport string
    is passed (exercises the 'if transport not in {...}' branch).
    """
    with pytest.raises(ValueError, match="Unsupported transport"):
        async with live_client(
            "http://example.com", transport="something-else"
        ):
            # We should never enter this block
            pass
