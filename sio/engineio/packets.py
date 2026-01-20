# engineio/packets.py
from __future__ import annotations

import base64
from collections.abc import Iterable
from dataclasses import dataclass
import json
import logging

from .constants import (
    MAX_PAYLOAD_BYTES,
    PING_INTERVAL_MS,
    PING_TIMEOUT_MS,
    RECORD_SEPARATOR,
)

logger = logging.getLogger("sio." + __name__)


@dataclass
class Packet:
    """
    In-memory representation of an Engine.IO packet.

    type:
      "0" = open
      "1" = close
      "2" = ping
      "3" = pong
      "4" = message
      "5" = upgrade
      "6" = noop
    data:
      str for text payloads, bytes for binary.
    binary:
      True if data is bytes.

    """

    type: str
    data: str | bytes | None = None
    binary: bool = False


# --------------------------------------------------------------------------- #
# Open / text helpers
# --------------------------------------------------------------------------- #


def encode_open_packet(
    sid: str,
    upgrades: Iterable[str],
    ping_interval_ms: int = PING_INTERVAL_MS,
    ping_timeout_ms: int = PING_TIMEOUT_MS,
    max_payload: int = MAX_PAYLOAD_BYTES,
) -> str:
    """
    Engine.IO "open" packet (type 0) with JSON payload.
    """
    upgrades_list = list(upgrades)
    payload = {
        "sid": sid,
        "upgrades": upgrades_list,
        "pingInterval": ping_interval_ms,
        "pingTimeout": ping_timeout_ms,
        "maxPayload": max_payload,
    }
    logger.debug(
        """
        encode_open_packet sid=%s upgrades=%s pingInterval=%d pingTimeout=%d
        maxPayload=%d
        """,
        sid,
        upgrades_list,
        ping_interval_ms,
        ping_timeout_ms,
        max_payload,
    )
    return "0" + json.dumps(payload, separators=(",", ":"))


def encode_text_packet(packet_type: str, data: str = "") -> str:
    """
    Encode a text Engine.IO packet into the "<type>[<data>]" wire format.
    """
    logger.debug(
        "encode_text_packet type=%s data_preview=%r",
        packet_type,
        (data or "")[:200],
    )
    return packet_type + (data or "")


# --------------------------------------------------------------------------- #
# HTTP long-polling encoding/decoding (with base64 for binary)
# --------------------------------------------------------------------------- #


def encode_http_binary_message(data: bytes) -> str:
    """
    Encode a binary *message* packet for HTTP long-polling.

    Spec: "Binary payloads MUST be base64-encoded and prefixed with a `b`
    character." Example: "4hello\\x1ebAQIDBA==".

    Here we follow the spec literally and treat "b<base64>" as a binary
    message packet (type 4 with binary payload).

    """
    logger.debug("encode_http_binary_message bytes=%d", len(data))
    b64 = base64.b64encode(data).decode("ascii")
    return "b" + b64


def encode_http_payload(parts: Iterable[str]) -> str:
    """
    Concatenate already-encoded packet segments with record separators:

        <packet><RS><packet><RS>...
    """
    parts_list = list(parts)
    logger.debug("encode_http_payload segments=%d", len(parts_list))
    encoded: list[str] = []
    for part in parts_list:
        if encoded:
            encoded.append(RECORD_SEPARATOR)
        encoded.append(part)
    payload = "".join(encoded)
    logger.debug("encode_http_payload result_len=%d", len(payload))
    return payload


def decode_http_payload(body: bytes) -> list[Packet]:
    """
    Decode HTTP long-polling payload into Packet objects.

    Text case (spec "Packet encoding / HTTP long-polling"):
        <type>[<data>]<RS><type>[<data>]...

    Binary case:
      - segment starts with 'b'
      - remainder is base64 for a binary *message* payload

    We normalize both into Packet instances with:
      - type="4" and binary=True for 'b...' segments
      - type="<char>" and binary=False for others

    """
    if not body:
        logger.debug("decode_http_payload empty body")
        return []

    text = body.decode("utf-8")
    segments = text.split(RECORD_SEPARATOR)
    logger.debug(
        "decode_http_payload raw_len=%d segments=%d",
        len(body),
        len(segments),
    )
    packets: list[Packet] = []

    for segment in segments:
        if not segment:
            continue

        if segment[0] == "b":
            # Binary message: b<base64(payload)>
            b64 = segment[1:]
            try:
                raw = base64.b64decode(b64)
            except Exception as exc:  # pragma: no cover
                logger.error("Invalid base64 payload: %s", exc)
                raise ValueError(f"Invalid base64 payload: {exc}") from exc

            logger.debug("Decoded HTTP binary message len=%d", len(raw))
            packets.append(Packet(type="4", data=raw, binary=True))
        else:
            p_type = segment[0]
            p_data = segment[1:] if len(segment) > 1 else ""
            logger.debug(
                "Decoded HTTP text packet type=%s data_len=%d",
                p_type,
                len(p_data),
            )
            packets.append(
                Packet(type=p_type, data=p_data or "", binary=False)
            )

    return packets


# --------------------------------------------------------------------------- #
# WebSocket encoding/decoding (binary frames "as is")
# --------------------------------------------------------------------------- #


def decode_ws_text_frame(text_data: str) -> Packet:
    """
    Decode a WebSocket text frame carrying a single Engine.IO packet:

    "<type>[<data>]"

    Text payload is always UTF-8.

    """
    if not text_data:
        logger.error("Empty WebSocket text frame")
        raise ValueError("Empty WebSocket text frame")

    p_type = text_data[0]
    p_data = text_data[1:] if len(text_data) > 1 else ""
    logger.debug(
        "decode_ws_text_frame type=%s data_len=%d",
        p_type,
        len(p_data),
    )
    return Packet(type=p_type, data=p_data, binary=False)


def decode_ws_binary_frame(bytes_data: bytes) -> Packet:
    """
    Decode a WebSocket binary frame carrying a single Engine.IO packet:

    <type-byte><binary-data>

    where <type-byte> is the ASCII code of the packet type ('0'..'6', '4' for
    message). Binary payload is sent "as is" per spec.

    """
    if not bytes_data:
        logger.error("Empty WebSocket binary frame")
        raise ValueError("Empty WebSocket binary frame")

    p_type = chr(bytes_data[0])
    p_data = bytes_data[1:]
    logger.debug(
        "decode_ws_binary_frame type=%s data_len=%d",
        p_type,
        len(p_data),
    )
    return Packet(type=p_type, data=p_data, binary=True)


def encode_ws_text_frame(packet_type: str, data: str = "") -> str:
    """
    Encode a Packet into a WebSocket text frame: "<type>[<data>]".
    """
    frame = encode_text_packet(packet_type, data)
    logger.debug(
        "encode_ws_text_frame type=%s frame_len=%d",
        packet_type,
        len(frame),
    )
    return frame


def encode_ws_binary_frame(packet_type: str, data: bytes) -> bytes:
    """
    Encode a Packet into a WebSocket binary frame: <type-byte><binary-data>.
    """
    frame = packet_type.encode("ascii") + (data or b"")
    logger.debug(
        "encode_ws_binary_frame type=%s frame_len=%d",
        packet_type,
        len(frame),
    )
    return frame
