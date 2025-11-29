from __future__ import annotations

import pytest

from sio.socketio.constants import (
    SIO_ACK,
    SIO_BINARY_ACK,
    SIO_BINARY_EVENT,
    SIO_DISCONNECT,
    SIO_EVENT,
)
from sio.socketio.protocol import SocketIOPacket
from sio.socketio.socket import NamespaceSocket


class DummyEio:
    def __init__(self):
        self._session = type(
            "Sess",
            (),
            {"transport": "polling", "websocket": None},
        )()
        self.text = []
        self.binary = []

    async def _send_text(self, text: str):
        self.text.append(text)

    async def _send_binary(self, data: bytes):
        self.binary.append(data)


class DummyServer:
    def __init__(self):
        self.disconnected = []
        self.forced = []

    def _group_name(self, namespace: str, room: str) -> str:
        # Simplified, but matches signature used by NamespaceSocket.join/leave
        return f"sio_{namespace.strip('/')}_{room}"

    async def _on_client_disconnect(self, ns_socket, reason: str):
        self.disconnected.append((ns_socket.id, reason))

    async def _dispatch_event(self, socket, event, args, ack_cb):
        # Not used in this file; tested at server level
        pass

    async def _force_disconnect_bad_packet(self, ns_socket, reason: str):
        self.forced.append((ns_socket.id, reason))


@pytest.mark.asyncio
async def test_send_and_emit_without_and_with_ack():
    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(
        server=server,
        eio=eio,
        namespace="/chat",
        id="sock1",
    )

    await sock.send({"foo": "bar"})
    assert len(eio.text) == 1
    header1 = eio.text[0]
    assert header1.startswith("2/chat,")
    assert '["message",{"foo":"bar"}]' in header1

    async def cb(*args):
        cb.called = args

    await sock.emit("evt", {"x": 1}, callback=cb)
    assert len(eio.text) == 2
    header2 = eio.text[1]
    assert header2.startswith("2/chat,")
    # extract id between comma and '['
    id_str = header2.split(",", 1)[1].split("[", 1)[0]
    assert id_str.isdigit()
    ack_id = int(id_str)
    assert ack_id in sock._pending_acks


@pytest.mark.asyncio
async def test_disconnect_calls_server_and_sends_packet():
    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(
        server=server, eio=eio, namespace="/chat", id="sock2"
    )

    await sock.disconnect()
    assert len(eio.text) == 1
    header = eio.text[0]
    assert header.startswith("1/chat,")

    assert server.disconnected == [("sock2", "client_disconnect")]


@pytest.mark.asyncio
async def test_join_leave_and_leave_all_rooms_with_ws_layer():
    server = DummyServer()
    eio = DummyEio()

    class DummyLayer:
        def __init__(self):
            self.added = []
            self.discarded = []

        async def group_add(self, group, channel_name):
            self.added.append((group, channel_name))

        async def group_discard(self, group, channel_name):
            self.discarded.append((group, channel_name))

    class DummyWS:
        def __init__(self):
            self.channel_layer = DummyLayer()
            self.channel_name = "chan"

    eio._session.websocket = DummyWS()

    sock = NamespaceSocket(
        server=server, eio=eio, namespace="/nsp", id="sock3"
    )

    await sock.join("room")
    assert "room" in sock.rooms
    assert eio._session.websocket.channel_layer.added
    group, channel = eio._session.websocket.channel_layer.added[0]
    assert channel == "chan"
    assert "room" in group

    # joining again: no second group_add
    added_before = list(eio._session.websocket.channel_layer.added)
    await sock.join("room")
    assert eio._session.websocket.channel_layer.added == added_before

    # leave unknown room: no error
    await sock.leave("other")

    await sock.leave("room")
    assert "room" not in sock.rooms
    assert eio._session.websocket.channel_layer.discarded

    # leave_all when empty: no error
    await sock.leave_all()
    assert not sock.rooms


@pytest.mark.asyncio
async def test_join_leave_without_websocket_or_channel_layer():
    server = DummyServer()
    eio = DummyEio()
    eio._session.websocket = None

    sock = NamespaceSocket(
        server=server, eio=eio, namespace="/nsp", id="sock4"
    )
    await sock.join("room")
    assert "room" in sock.rooms
    await sock.leave("room")
    assert not sock.rooms


@pytest.mark.asyncio
async def test_handle_event_and_ack_from_client():
    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(server=server, eio=eio, id="sock5")

    # valid event without ack
    pkt = type(
        "Pkt", (), {"type": SIO_EVENT, "data": ["evt", {"x": 1}], "id": None}
    )
    await sock._handle_event(pkt)

    # valid event with ack id (we only check it doesn't crash and sends ACK
    # when called)
    pkt2 = type("Pkt", (), {"type": SIO_EVENT, "data": ["evt"], "id": 7})
    await sock._handle_event(pkt2)
    # we won't call the ack callback here; server-level tests cover ack
    # round-trip


@pytest.mark.asyncio
async def test_handle_event_with_bad_payload_forces_disconnect():
    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(server=server, eio=eio, id="sock6")

    bad_pkt = type("Pkt", (), {"type": SIO_EVENT, "data": None, "id": None})
    await sock._handle_event(bad_pkt)
    assert server.forced == [("sock6", "bad_event_payload")]


@pytest.mark.asyncio
async def test_handle_ack_branches():
    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(server=server, eio=eio, id="sock7")

    # id None -> ignore
    pkt_no_id = type(
        "Pkt", (), {"type": SIO_ACK, "id": None, "data": ["ignored"]}
    )
    await sock._handle_ack(pkt_no_id)

    # no pending callback -> ignore
    pkt_unknown = type(
        "Pkt", (), {"type": SIO_ACK, "id": 999, "data": ["ignored"]}
    )
    await sock._handle_ack(pkt_unknown)

    # happy path: callback
    called = {}

    async def cb(*args):
        called["args"] = args

    sock._pending_acks[1] = cb
    pkt_list = type("Pkt", (), {"type": SIO_ACK, "id": 1, "data": [1, 2]})
    await sock._handle_ack(pkt_list)
    assert called["args"] == (1, 2)

    called.clear()
    sock._pending_acks[2] = cb
    pkt_scalar = type("Pkt", (), {"type": SIO_ACK, "id": 2, "data": 42})
    await sock._handle_ack(pkt_scalar)
    assert called["args"] == (42,)


@pytest.mark.asyncio
async def test_handle_packet_from_client_switches_by_type():
    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(server=server, eio=eio, id="sock8")

    pkt_evt = type("Pkt", (), {"type": SIO_EVENT, "data": ["evt"], "id": None})
    await sock._handle_packet_from_client(pkt_evt)

    pkt_bin_evt = type(
        "Pkt", (), {"type": SIO_BINARY_EVENT, "data": ["evt"], "id": None}
    )
    await sock._handle_packet_from_client(pkt_bin_evt)

    pkt_ack = type("Pkt", (), {"type": SIO_ACK, "id": None, "data": None})
    await sock._handle_packet_from_client(pkt_ack)

    pkt_b_ack = type(
        "Pkt", (), {"type": SIO_BINARY_ACK, "id": None, "data": None}
    )
    await sock._handle_packet_from_client(pkt_b_ack)

    pkt_disc = type(
        "Pkt", (), {"type": SIO_DISCONNECT, "id": None, "data": None}
    )
    await sock._handle_packet_from_client(pkt_disc)
    assert server.disconnected  # disconnect path taken


@pytest.mark.asyncio
async def test_namespace_socket_ack_sends_ack_packet():
    """
    When a client event has an ack id, _handle_event should build a SIO_ACK
    packet with the same id and the ack args, and send it via _send_packet().
    """

    class DummyServer:
        async def _dispatch_event(self, socket, event, args, ack_cb):
            # Simulate user handler calling ack(...)
            assert event == "my_event"
            assert args == ["arg1"]
            await ack_cb("ok", 42)

    class DummyEio:
        def __init__(self):
            self._session = type("S", (), {"transport": "polling"})()

    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(
        server=server, eio=eio, namespace="/ns", id="sock-1"
    )

    sent_packets: list[SocketIOPacket] = []

    async def fake_send_packet(pkt: SocketIOPacket):
        sent_packets.append(pkt)

    sock._send_packet = fake_send_packet  # type: ignore[assignment]

    pkt = SocketIOPacket(
        type=SIO_EVENT,
        namespace="/ns",
        data=["my_event", "arg1"],
        id=7,  # ack id from client
    )

    await sock._handle_event(pkt)

    # Exactly one ACK should have been sent
    assert len(sent_packets) == 1
    ack_pkt = sent_packets[0]
    assert ack_pkt.type == SIO_ACK
    assert ack_pkt.namespace == "/ns"
    assert ack_pkt.id == 7
    assert ack_pkt.data == ["ok", 42]


@pytest.mark.asyncio
async def test_namespace_socket_leave_all_calls_leave_for_each_room():
    """
    leave_all() should call leave(room) once per room in self.rooms, using a
    copy of the set to avoid mutation issues.
    """

    class DummyServer:
        async def _dispatch_event(self, *a, **k):
            pass

    class DummyEio:
        def __init__(self):
            self._session = type("S", (), {"transport": "polling"})()

    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(
        server=server, eio=eio, namespace="/ns", id="sock-2"
    )

    sock.rooms = {"room1", "room2", "room3"}

    calls: list[str] = []

    async def fake_leave(room: str):
        calls.append(room)

    sock.leave = fake_leave  # type: ignore[assignment]

    await sock.leave_all()

    assert set(calls) == {"room1", "room2", "room3"}


@pytest.mark.asyncio
async def test_namespace_socket_send_packet_sends_binary_attachments():
    """
    _send_packet() should call eio._send_binary(blob) once per attachment
    returned by encode_packet_to_eio().
    """

    class DummyServer:
        async def _dispatch_event(self, *a, **k):
            pass

    class DummyEio:
        def __init__(self):
            self.sent_text = []
            self.sent_bin = []
            # minimal session object
            self._session = type("S", (), {"transport": "polling"})()

        async def _send_text(self, header: str):
            self.sent_text.append(header)

        async def _send_binary(self, blob: bytes):
            self.sent_bin.append(blob)

    server = DummyServer()
    eio = DummyEio()
    sock = NamespaceSocket(
        server=server, eio=eio, namespace="/bin", id="sock-3"
    )

    blob1 = b"\x01\x02"
    blob2 = b"\x03\x04"

    pkt = SocketIOPacket(
        type=SIO_EVENT,
        namespace="/bin",
        data=["my_event", blob1, blob2],
    )

    await sock._send_packet(pkt)

    # One text header plus both binary blobs should be sent
    assert len(eio.sent_text) == 1
    # Order is preserved by encode_packet_to_eio
    assert eio.sent_bin == [blob1, blob2]
