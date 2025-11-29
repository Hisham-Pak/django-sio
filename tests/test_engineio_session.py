from __future__ import annotations

import pytest

from sio.engineio import session as session_mod
from sio.engineio.constants import (
    PING_INTERVAL_MS,
    PING_TIMEOUT_MS,
    RECORD_SEPARATOR,
)
from sio.engineio.session import (
    EngineIOSession,
    create_session,
    destroy_session,
    get_session,
)


@pytest.mark.asyncio
async def test_enqueue_and_http_next_payload_happy_path(monkeypatch):
    sess = EngineIOSession("sid")

    await sess.enqueue_http_packet("4hello")
    await sess.enqueue_http_packet("2")

    payload = await sess.http_next_payload(timeout=0.1)
    text = payload.decode("utf-8")
    assert text == f"4hello{RECORD_SEPARATOR}2"


@pytest.mark.asyncio
async def test_http_next_payload_timeout_returns_empty():
    sess = EngineIOSession("sid")

    # nothing queued: should timeout and return b""
    body = await sess.http_next_payload(timeout=0.01)
    assert body == b""


@pytest.mark.asyncio
async def test_http_next_payload_respects_max_payload(monkeypatch):
    # Force a very small MAX_PAYLOAD_BYTES in this module to trigger split
    import sio.engineio.session as session_mod

    monkeypatch.setattr(session_mod, "MAX_PAYLOAD_BYTES", 10)

    sess = EngineIOSession("sid")

    # "4abcdef" (7 bytes) + RS (1 byte) + "4xyz" (4 bytes) > 10
    await sess.enqueue_http_packet("4abcdef")
    await sess.enqueue_http_packet("4xyz")

    payload1 = await sess.http_next_payload(timeout=0.1)
    text1 = payload1.decode("utf-8")
    assert text1 == "4abcdef"

    payload2 = await sess.http_next_payload(timeout=0.1)
    text2 = payload2.decode("utf-8")
    assert text2 == "4xyz"


@pytest.mark.asyncio
async def test_enqueue_noop_if_closed():
    sess = EngineIOSession("sid")
    sess.closed = True
    await sess.enqueue_http_packet("4hello")

    body = await sess.http_next_payload(timeout=0.01)
    assert body == b""


def test_should_send_ping_and_closed_branch(monkeypatch):
    import sio.engineio.session as session_mod

    # start at deterministic time
    t = 1_000.0

    def fake_time():
        return t

    monkeypatch.setattr(session_mod.time, "time", fake_time)

    sess = EngineIOSession("sid")

    # no ping sent yet -> should send
    assert sess.should_send_ping()

    sess.mark_ping_sent()
    assert not sess.should_send_ping()

    # advance by less than interval
    t += (PING_INTERVAL_MS / 1000.0) / 2
    assert not sess.should_send_ping()

    # advance beyond interval
    t += PING_INTERVAL_MS / 1000.0
    assert sess.should_send_ping()

    # if closed, should never send
    sess.closed = True
    assert not sess.should_send_ping()


def test_is_timed_out_branches(monkeypatch):
    import sio.engineio.session as session_mod

    base = 2_000.0

    def fake_time():
        return base

    monkeypatch.setattr(session_mod.time, "time", fake_time)

    sess = EngineIOSession("sid")

    # immediately after init -> not timed out
    assert not sess.is_timed_out()

    # closed sessions are always considered timed out
    sess.closed = True
    assert sess.is_timed_out()

    # reopen and test threshold logic
    sess.closed = False
    sess.mark_pong_received()

    timeout_ms = 2 * (PING_INTERVAL_MS + PING_TIMEOUT_MS)

    base += (timeout_ms / 1000.0) - 0.001
    assert not sess.is_timed_out()

    base += 0.01
    assert sess.is_timed_out()


@pytest.mark.asyncio
async def test_http_next_payload_segment_too_large_returns_empty_and_requeues(
    monkeypatch,
):
    """
    When the queued segment is larger than MAX_PAYLOAD_BYTES, http_next_payload
    should:

    - requeue the segment,
    - return b'' (because payload_parts stays empty),
    - still allow the segment to be delivered on a subsequent call when the
      limit is larger.
    """
    sess = session_mod.EngineIOSession("sid-large")

    # Force a very small max payload so nothing fits
    monkeypatch.setattr(session_mod, "MAX_PAYLOAD_BYTES", 1)

    # Enqueue a segment that is definitely too large
    await sess.enqueue_http_packet("abcd")

    # First call: segment is requeued, no payload_parts -> returns b""
    body = await sess.http_next_payload(timeout=0.01)
    assert body == b""

    # Now allow it to fit and make sure it comes out
    monkeypatch.setattr(session_mod, "MAX_PAYLOAD_BYTES", 10)
    body2 = await sess.http_next_payload(timeout=0.01)
    assert body2 == b"abcd"


@pytest.mark.asyncio
async def test_destroy_session_removes_session_from_registry():
    """
    destroy_session(sid) should remove the session from the global registry and
    be safe to call even if the sid no longer exists.
    """
    # Create a real session so it is registered
    sess = await create_session()
    sid = sess.sid

    # Sanity check: session is present
    assert await get_session(sid) is sess

    # Destroy it
    await destroy_session(sid)
    assert await get_session(sid) is None

    # Calling again must not raise (pop with default None)
    await destroy_session(sid)
