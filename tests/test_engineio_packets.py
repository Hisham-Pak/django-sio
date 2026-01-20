from __future__ import annotations

import base64
from importlib import reload
import json

from django.test import override_settings
import pytest

from sio.engineio.constants import RECORD_SEPARATOR
from sio.engineio.packets import (
    Packet,
    decode_http_payload,
    decode_ws_binary_frame,
    decode_ws_text_frame,
    encode_http_binary_message,
    encode_http_payload,
    encode_open_packet,
    encode_text_packet,
    encode_ws_binary_frame,
    encode_ws_text_frame,
)


def test_encode_open_packet_content():
    pkt = encode_open_packet(
        sid="abc",
        upgrades=["websocket"],
        ping_interval_ms=10,
        ping_timeout_ms=20,
        max_payload=42,
    )
    assert pkt.startswith("0")
    payload = json.loads(pkt[1:])
    assert payload == {
        "sid": "abc",
        "upgrades": ["websocket"],
        "pingInterval": 10,
        "pingTimeout": 20,
        "maxPayload": 42,
    }


def test_encode_text_packet_empty_and_non_empty():
    assert encode_text_packet("2") == "2"
    assert encode_text_packet("4", "hello") == "4hello"
    # falsy payload → just type
    assert encode_text_packet("4", "") == "4"


def test_encode_http_binary_message_matches_base64():
    data = b"\x00\x01\x02"
    seg = encode_http_binary_message(data)
    assert seg.startswith("b")
    decoded = base64.b64decode(seg[1:])
    assert decoded == data


def test_encode_http_payload_zero_one_many():
    assert encode_http_payload([]) == ""

    one = encode_http_payload(["4one"])
    assert one == "4one"

    many = encode_http_payload(["4one", "4two", "4three"])
    assert many == f"4one{RECORD_SEPARATOR}4two{RECORD_SEPARATOR}4three"


def test_decode_http_payload_text_and_binary():
    parts = ["4hello", encode_http_binary_message(b"\x01\x02")]
    payload = encode_http_payload(parts).encode("utf-8")

    packets = decode_http_payload(payload)
    assert len(packets) == 2

    p1, p2 = packets
    assert p1 == Packet(type="4", data="hello", binary=False)
    assert p2.type == "4"
    assert p2.binary is True
    assert p2.data == b"\x01\x02"


def test_decode_http_payload_empty_body():
    assert decode_http_payload(b"") == []


def test_decode_http_payload_ignores_empty_segments():
    payload = f"{RECORD_SEPARATOR}4foo{RECORD_SEPARATOR}".encode()
    packets = decode_http_payload(payload)
    assert len(packets) == 1
    assert packets[0].data == "foo"


def test_decode_http_payload_invalid_base64_raises():
    # 'AA' is invalid base64 for our use (incorrect padding)
    bad_segment = b"bAA"
    with pytest.raises(ValueError):
        decode_http_payload(bad_segment)


def test_decode_ws_text_frame_roundtrip_and_error():
    frame = encode_ws_text_frame("4", "payload")
    pkt = decode_ws_text_frame(frame)
    assert pkt == Packet(type="4", data="payload", binary=False)

    with pytest.raises(ValueError):
        decode_ws_text_frame("")


def test_decode_ws_binary_frame_roundtrip_and_error():
    frame = encode_ws_binary_frame("4", b"\x10\x20")
    pkt = decode_ws_binary_frame(frame)
    assert pkt == Packet(type="4", data=b"\x10\x20", binary=True)

    with pytest.raises(ValueError):
        decode_ws_binary_frame(b"")


def test_encode_open_packet_uses_django_settings_defaults():
    """
    When Django settings define SIO_ENGINEIO_* values, encode_open_packet()
    called *without* explicit timing/payload args should advertise those values
    in the open packet.

    We use override_settings as a context manager and reload the modules
    inside that context so that:

      - engineio.constants re-reads Django settings
      - engineio.packets recomputes its default argument values

    Then we reload them again after the context to restore the original
    defaults for the rest of the test suite.

    """
    from sio.engineio import constants as const_mod, packets as packets_mod

    # First, make sure we're starting from a clean baseline
    reload(const_mod)
    reload(packets_mod)

    with override_settings(
        SIO_ENGINEIO_PING_INTERVAL_MS=10,
        SIO_ENGINEIO_PING_TIMEOUT_MS=20,
        SIO_ENGINEIO_MAX_PAYLOAD_BYTES=42,
    ):
        # Re-evaluate constants and encode_open_packet defaults with the
        # overridden settings applied.
        reload(const_mod)
        reload(packets_mod)

        pkt = packets_mod.encode_open_packet(
            sid="abc",
            upgrades=["websocket"],
            # no explicit ping_interval_ms / ping_timeout_ms / max_payload
        )
        assert pkt.startswith("0")
        payload = json.loads(pkt[1:])

        assert payload == {
            "sid": "abc",
            "upgrades": ["websocket"],
            "pingInterval": 10,
            "pingTimeout": 20,
            "maxPayload": 42,
        }

    # After leaving override_settings, Django settings are back to their
    # original values. Reload modules again so other tests see the default
    # constants.
    reload(const_mod)
    reload(packets_mod)
