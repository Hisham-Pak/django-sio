from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .constants import (
    DEFAULT_NAMESPACE,
    SIO_ACK,
    SIO_BINARY_ACK,
    SIO_BINARY_EVENT,
    SIO_EVENT,
)

JSONData = Any  # we accept list/dict/str/number/None


@dataclass
class SocketIOPacket:
    """
    In-memory representation of a Socket.IO packet (protocol v5).
    """

    type: int
    namespace: str = DEFAULT_NAMESPACE
    data: JSONData | None = None
    id: int | None = None
    # for binary packets, this is how many binary attachments we expect/send
    attachments: int = 0

    def is_binary(self) -> bool:
        return self.type in (SIO_BINARY_EVENT, SIO_BINARY_ACK)


# --------------------------------------------------------------------------- #
# Helpers to find/remove/re-add binary attachments (placeholder algorithm)
# --------------------------------------------------------------------------- #

PLACEHOLDER_KEY = "_placeholder"
PLACEHOLDER_NUM = "num"


def _is_binary(x: Any) -> bool:
    return isinstance(x, (bytes, bytearray, memoryview))


def _deconstruct_data(data: JSONData) -> tuple[JSONData, list[bytes]]:
    """
    Recursively walk `data`, extract binary objects (bytes, bytearray,
    memoryview), replace them by placeholder objects of the form:

    {"_placeholder": true, "num": <index>} and return (data_without_binary,
    attachments_list).

    """
    attachments: list[bytes] = []

    def _walk(obj: Any) -> Any:
        if _is_binary(obj):
            idx = len(attachments)
            attachments.append(bytes(obj))  # normalize to bytes
            return {PLACEHOLDER_KEY: True, PLACEHOLDER_NUM: idx}

        if isinstance(obj, list):
            return [_walk(item) for item in obj]

        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}

        # leave everything else untouched
        return obj

    return _walk(data), attachments


def _reconstruct_data(data: JSONData, attachments: list[bytes]) -> JSONData:
    """
    Recursively walk `data`, replace placeholder objects with actual binary
    attachments from `attachments` list.
    """

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict) and obj.get(PLACEHOLDER_KEY) is True:
            num = obj.get(PLACEHOLDER_NUM)
            if isinstance(num, int) and 0 <= num < len(attachments):
                return attachments[num]
            return None  # malformed placeholder

        if isinstance(obj, list):
            return [_walk(item) for item in obj]

        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}

        return obj

    return _walk(data)


# --------------------------------------------------------------------------- #
# Encoding Socket.IO packets into Engine.IO "message" payload strings/frames
# --------------------------------------------------------------------------- #


def encode_packet_to_eio(
    pkt: SocketIOPacket,
) -> tuple[str, list[bytes]]:
    """
    Encode a Socket.IO packet into:

    - a *string* payload for the first Engine.IO "message" packet
    - a list of binary attachments (bytes), each sent as a separate
      Engine.IO *binary* message packet.

    """
    p_type = pkt.type
    nsp = pkt.namespace or DEFAULT_NAMESPACE
    data = pkt.data
    pack_attachments = 0
    attachments: list[bytes] = []

    # Decide if this is a binary packet and extract attachments
    if p_type in (SIO_EVENT, SIO_ACK):
        if data is not None:
            deconstructed_data, attachments = _deconstruct_data(data)
            if attachments:
                pack_attachments = len(attachments)
                # Upgrade to binary packet type
                p_type = (
                    SIO_BINARY_EVENT if p_type == SIO_EVENT else SIO_BINARY_ACK
                )
                data = deconstructed_data

    elif p_type in (SIO_BINARY_EVENT, SIO_BINARY_ACK) and data is not None:
        deconstructed_data, attachments = _deconstruct_data(data)
        pack_attachments = len(attachments)
        data = deconstructed_data

    # Build header string according to spec format
    # <packet type>[<#attachments>-][<namespace>,][<ack id>][JSON]
    parts: list[str] = []

    # 1) type
    parts.append(str(p_type))

    # 2) attachments count (for binary packets)
    if p_type in (SIO_BINARY_EVENT, SIO_BINARY_ACK):
        parts.append(str(pack_attachments))
        parts.append("-")

    # 3) namespace (if not default "/")
    include_namespace = nsp != DEFAULT_NAMESPACE
    if include_namespace:
        parts.append(nsp)
        parts.append(",")

    # 4) ack id (if present)
    if pkt.id is not None:
        # If namespace was default and no comma added, we don't add a comma
        # here.
        # For default namespace, id goes immediately after type/attachments.
        parts.append(str(pkt.id))

    # 5) JSON payload
    if data is not None:
        json_str = json.dumps(data, separators=(",", ":"))
        parts.append(json_str)

    header = "".join(parts)
    return header, attachments


# --------------------------------------------------------------------------- #
# Decoding Engine.IO "message" payloads to Socket.IO packets
# --------------------------------------------------------------------------- #


@dataclass
class _BinaryAccum:
    """
    Internal state for accumulating attachments for one BINARY_EVENT/ACK.
    """

    pkt: SocketIOPacket
    expected: int
    buffers: list[bytes]


class SocketIOParser:
    """
    Per-Engine.IO-connection parser.

    You feed it Engine.IO "message" payloads (text or binary) and it yields
    completed Socket.IO packets (possibly zero or more).

    """

    def __init__(self):
        self._binary_accum: _BinaryAccum | None = None

    def feed_eio_message(
        self,
        payload: str | bytes,
        binary: bool,
    ) -> list[SocketIOPacket]:
        """
        Feed one Engine.IO message (already stripped of its "4"/binary header)
        and return any completed Socket.IO packets.

        For HTTP polling:
          - text payloads are e.g. "2[\"foo\"]"
          - binary payloads are raw bytes (attachments)

        For WebSocket:
          - text frames are the same as above
          - binary frames are also raw bytes attachments.

        """
        if binary:
            return self._handle_binary_attachment(bytes(payload))

        # text message
        return self._handle_text(str(payload))

    # -- text ------------------------------------------------------------ #

    def _handle_text(self, text: str) -> list[SocketIOPacket]:
        if not text:
            return []

        # If we are in the middle of accumulating a binary packet header,
        # text frames are not expected here (per spec), but we'll just ignore.
        if self._binary_accum is not None:
            # Spec doesn't mention this case; safest is to drop state.
            self._binary_accum = None
            return []

        # First char: packet type
        first = text[0]
        if not first.isdigit():
            # malformed
            return []

        p_type = int(first)
        rest = text[1:]

        pkt = SocketIOPacket(type=p_type, namespace=DEFAULT_NAMESPACE)

        # Handle CONNECT_ERROR (4) special-case: data only
        # handled by generic decoder as well, no need to special-case here.

        # For BINARY_EVENT/BINARY_ACK, parse "#-"
        attachments = 0
        if p_type in (SIO_BINARY_EVENT, SIO_BINARY_ACK):
            # digits until '-'
            num_str = ""
            i = 0
            while i < len(rest) and rest[i].isdigit():
                num_str += rest[i]
                i += 1
            if i < len(rest) and rest[i] == "-" and num_str:
                attachments = int(num_str)
                i += 1
                rest = rest[i:]
            else:
                # malformed; drop
                return []
        # Now parse namespace if present
        namespace = DEFAULT_NAMESPACE
        ack_id: int | None = None
        json_data: JSONData | None = None

        # Namespace is included if it starts with "/" and is followed by ","
        if rest.startswith("/"):
            # namespace until first ','
            idx = rest.find(",")
            if idx == -1:
                # no comma → malformed
                return []
            namespace = rest[:idx] or DEFAULT_NAMESPACE
            rest = rest[idx + 1 :]
        pkt.namespace = namespace

        # Next, if remaining starts with digits, that's ack id
        i = 0
        id_str = ""
        while i < len(rest) and rest[i].isdigit():
            id_str += rest[i]
            i += 1
        if id_str:
            ack_id = int(id_str)
            rest = rest[i:]
        pkt.id = ack_id

        # Remaining, if any, is JSON payload
        if rest:
            try:
                json_data = json.loads(rest)
            except json.JSONDecodeError:
                json_data = None
        pkt.data = json_data

        # If binary packet, we now need attachments
        if p_type in (SIO_BINARY_EVENT, SIO_BINARY_ACK):
            pkt.attachments = attachments
            self._binary_accum = _BinaryAccum(
                pkt=pkt,
                expected=attachments,
                buffers=[],
            )
            # We don't yield the packet yet, attachments pending.
            return []

        # Non-binary: we can yield immediately
        return [pkt]

    # -- binary ---------------------------------------------------------- #

    def _handle_binary_attachment(self, data: bytes) -> list[SocketIOPacket]:
        if self._binary_accum is None:
            # Unexpected binary; ignore
            return []

        accum = self._binary_accum
        accum.buffers.append(data)

        if len(accum.buffers) < accum.expected:
            # still waiting for more
            return []

        # We have all attachments, reconstruct data
        pkt = accum.pkt
        if pkt.data is not None:
            pkt.data = _reconstruct_data(pkt.data, accum.buffers)

        self._binary_accum = None
        return [pkt]
