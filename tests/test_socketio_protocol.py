from __future__ import annotations

import json

from sio.socketio.constants import (
    DEFAULT_NAMESPACE,
    SIO_ACK,
    SIO_BINARY_ACK,
    SIO_BINARY_EVENT,
    SIO_EVENT,
)
from sio.socketio.protocol import (
    PLACEHOLDER_KEY,
    PLACEHOLDER_NUM,
    SocketIOPacket,
    SocketIOParser,
    _deconstruct_data,
    _reconstruct_data,
    encode_packet_to_eio,
)


def test_deconstruct_and_reconstruct_binary_data():
    data = ["evt", {"buf": b"\x00\x01", "nested": [b"\x02"]}]

    without_bin, attachments = _deconstruct_data(data)
    assert len(attachments) == 2
    assert attachments[0] == b"\x00\x01"
    assert attachments[1] == b"\x02"

    ph1 = without_bin[1]["buf"]
    assert ph1[PLACEHOLDER_KEY] is True
    assert ph1[PLACEHOLDER_NUM] == 0

    restored = _reconstruct_data(without_bin, attachments)
    assert restored == data


def test_reconstruct_with_bad_placeholder():
    data = {"buf": {PLACEHOLDER_KEY: True, PLACEHOLDER_NUM: 99}}
    restored = _reconstruct_data(data, [b"\x00"])
    assert restored["buf"] is None


def test_encode_packet_event_and_ack_no_binary():
    pkt = SocketIOPacket(
        type=SIO_EVENT,
        namespace=DEFAULT_NAMESPACE,
        data=["test", {"x": 1}],
        id=None,
    )
    header, attachments = encode_packet_to_eio(pkt)
    assert attachments == []
    assert header.startswith("2")
    assert json.loads(header[1:]) == ["test", {"x": 1}]

    ack_pkt = SocketIOPacket(
        type=SIO_ACK,
        namespace="/chat",
        data=["ok"],
        id=42,
    )
    header2, attachments2 = encode_packet_to_eio(ack_pkt)
    assert attachments2 == []
    assert header2.startswith("3/chat,42")
    assert json.loads(header2.split("42", 1)[1]) == ["ok"]


def test_encode_packet_binary_event_and_binary_ack():
    pkt = SocketIOPacket(
        type=SIO_EVENT,
        namespace="/bin",
        data=["evt", {"b": b"\x01\x02"}],
    )
    header, attachments = encode_packet_to_eio(pkt)
    assert len(attachments) == 1
    assert attachments[0] == b"\x01\x02"

    assert header.startswith("51-/bin,")
    payload = json.loads(header.split(",", 1)[1])
    assert payload[0] == "evt"
    ph = payload[1]["b"]
    assert ph[PLACEHOLDER_KEY] is True
    assert ph[PLACEHOLDER_NUM] == 0

    pkt2 = SocketIOPacket(
        type=SIO_BINARY_ACK,
        namespace=DEFAULT_NAMESPACE,
        data=["ack", b"\x03", b"\x04"],
        id=7,
    )
    header2, attachments2 = encode_packet_to_eio(pkt2)
    assert header2.startswith("6")
    assert len(attachments2) == 2
    assert attachments2[0] == b"\x03"
    assert attachments2[1] == b"\x04"


def test_parser_simple_event_default_and_named_namespace():
    parser = SocketIOParser()

    packets = parser.feed_eio_message('2["ping",1]', binary=False)
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt.type == SIO_EVENT
    assert pkt.namespace == DEFAULT_NAMESPACE
    assert pkt.data == ["ping", 1]
    assert pkt.id is None

    packets2 = parser.feed_eio_message('2/chat,12["evt"]', binary=False)
    assert len(packets2) == 1
    pkt2 = packets2[0]
    assert pkt2.namespace == "/chat"
    assert pkt2.id == 12
    assert pkt2.data == ["evt"]


def test_parser_binary_event_full_flow_and_unexpected_binary_and_text():
    parser = SocketIOParser()

    header = '51-["bin",{"buf":{"_placeholder":true,"num":0}}]'

    # Start binary accumulation: header only, no packet yet
    packets = parser.feed_eio_message(header, binary=False)
    assert packets == []
    assert parser._binary_accum is not None

    # Unexpected text in the middle: spec undefined, your code drops state &
    # returns []
    packets = parser.feed_eio_message('2["other"]', binary=False)
    assert packets == []
    assert parser._binary_accum is None

    # Unexpected binary when not accumulating: ignored → []
    parser2 = SocketIOParser()
    packets2 = parser2.feed_eio_message(b"\x00\x01", binary=True)
    assert packets2 == []

    # Proper full binary flow
    parser3 = SocketIOParser()
    parser3.feed_eio_message(header, binary=False)
    packets3 = parser3.feed_eio_message(b"\x10\x20\x30", binary=True)
    assert len(packets3) == 1
    pkt = packets3[0]
    assert pkt.type == SIO_BINARY_EVENT
    assert pkt.attachments == 1
    assert isinstance(pkt.data, list)
    assert pkt.data[0] == "bin"
    assert pkt.data[1]["buf"] == b"\x10\x20\x30"


def test_parser_malformed_text_is_ignored_or_yields_none_data():
    parser = SocketIOParser()

    # Non-digit first char → ignored
    assert parser.feed_eio_message("x", binary=False) == []

    # Binary type with malformed attachments header → ignored
    assert parser.feed_eio_message("5bad", binary=False) == []

    # Namespace without comma → ignored
    assert parser.feed_eio_message("2/chat", binary=False) == []

    # Invalid JSON: data becomes None but packet still returned
    packets = parser.feed_eio_message('2["evt",]', binary=False)
    assert len(packets) == 1
    assert packets[0].data is None


def test_socketio_packet_is_binary_helper():
    """
    SocketIOPacket.is_binary() should be true only for BINARY_EVENT/BINARY_ACK
    and false for the regular EVENT/ACK types.
    """
    pkt_bin_event = SocketIOPacket(type=SIO_BINARY_EVENT)
    pkt_bin_ack = SocketIOPacket(type=SIO_BINARY_ACK)
    pkt_event = SocketIOPacket(type=SIO_EVENT)
    pkt_ack = SocketIOPacket(type=SIO_ACK)

    assert pkt_bin_event.is_binary() is True
    assert pkt_bin_ack.is_binary() is True
    assert pkt_event.is_binary() is False
    assert pkt_ack.is_binary() is False


def test_parser_empty_text_message_returns_empty_list():
    """
    Feeding an empty text Engine.IO message into SocketIOParser should return
    an empty list of packets (exercises the 'if not text' branch).
    """
    parser = SocketIOParser()

    packets = parser.feed_eio_message("", binary=False)

    assert packets == []


def test_parser_binary_attachment_waits_for_all_attachments():
    """
    When a binary event announces more than one attachment, feeding only some
    of the attachments should return an empty list and keep the accumulator
    around (len(buffers) < expected branch).
    """
    parser = SocketIOParser()

    # Binary EVENT packet header:
    # type = 5 (SIO_BINARY_EVENT)
    # "2-"  => 2 attachments
    # JSON payload with two placeholders (valid JSON, but content doesn't
    # matter for this test)
    header = (
        '52-["ev",{"_placeholder":true,"num":0},{"_placeholder":true,"num":1}]'
    )

    # First, feed the text header; this sets up _binary_accum with expected=2
    packets_from_header = parser.feed_eio_message(header, binary=False)
    assert packets_from_header == []
    assert parser._binary_accum is not None
    assert parser._binary_accum.expected == 2  # type: ignore[union-attr]

    # Now feed only the first binary attachment; since we still expect 2,
    # the parser should return [] and keep accumulating.
    packets_from_first_blob = parser.feed_eio_message(
        b"first-blob", binary=True
    )
    assert packets_from_first_blob == []

    # Accumulator should still be present with one buffer stored
    accum = parser._binary_accum
    assert accum is not None
    assert len(accum.buffers) == 1
    assert accum.expected == 2
