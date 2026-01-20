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

    # immediately after init -> not yet time to send a ping
    assert not sess.should_send_ping()

    # advance by less than interval
    t += (PING_INTERVAL_MS / 1000.0) / 2
    assert not sess.should_send_ping()

    # advance beyond interval -> now we should send a ping
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

    # Make EngineIOSession use our fake clock
    monkeypatch.setattr(session_mod.time, "time", fake_time)

    sess = EngineIOSession("sid")

    # immediately after init -> not timed out
    assert not sess.is_timed_out()

    # closed sessions are always considered timed out
    sess.closed = True
    assert sess.is_timed_out()

    # reopen and test threshold logic
    sess.closed = False
    sess.mark_pong_received()  # last_pong = base (2000.0)

    # New timeout definition: pingInterval + pingTimeout
    timeout_ms = PING_INTERVAL_MS + PING_TIMEOUT_MS

    # Just *below* the timeout threshold → not timed out
    base += (timeout_ms / 1000.0) - 0.001
    assert not sess.is_timed_out()

    # Just *above* the timeout threshold → timed out
    base += 0.01
    assert sess.is_timed_out()


@pytest.mark.asyncio
async def test_http_next_payload_segment_too_large(monkeypatch):
    """
    test_http_next_payload_segment_too_large_returns_single_segment
    _even_if_over_limit.

    When a *single* queued segment is larger than max_payload_bytes, the
    implementation still delivers that segment in one response, rather than
    dropping or requeueing it. The max_payload_bytes limit is only used to
    decide how many segments to bundle together.

    This complements test_http_next_payload_respects_max_payload, which covers
    splitting across multiple segments.

    """
    sess = session_mod.EngineIOSession("sid-large")

    # Force a very small per-session payload limit so this segment exceeds it.
    sess.max_payload_bytes = 1

    # Enqueue a segment that is definitely too large
    await sess.enqueue_http_packet("abcd")

    # We still get the full segment back in a single response
    body = await sess.http_next_payload(timeout=0.01)
    assert body == b"abcd"


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
