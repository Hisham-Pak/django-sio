from __future__ import annotations

import asyncio

import pytest
from sample_project.sampleapp.models import Message

import socketio

from .helpers import (
    LIVE_NAMESPACE,
    SOCKETIO_PATH,
    STATE_TIMEOUT,
    live_client,
    wait_for_state,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
async def test_basic_socketio_connect(live_server_url: str):
    sio = socketio.AsyncClient()
    connected = asyncio.Event()

    @sio.on("connect", namespace=LIVE_NAMESPACE)
    async def on_connect():
        connected.set()

    await sio.connect(
        live_server_url,
        socketio_path=SOCKETIO_PATH,
        namespaces=[LIVE_NAMESPACE],
        wait=True,
        wait_timeout=STATE_TIMEOUT,
    )

    try:
        # Wait for namespace connect callback to fire
        await asyncio.wait_for(connected.wait(), timeout=STATE_TIMEOUT)

        assert connected.is_set()
        assert sio.connected
        assert LIVE_NAMESPACE in sio.namespaces
    finally:
        # Now disconnect gracefully; no need for abort=True anymore
        try:
            await asyncio.wait_for(sio.disconnect(), timeout=STATE_TIMEOUT)
        except TimeoutError:
            # As a last resort, force abort if you really want
            await sio.eio.disconnect(abort=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["polling", "websocket"])
async def test_connect_sends_initial_state(
    live_server_url: str, transport: str
):
    """
    When a client connects to /live namespace, it should receive an initial
    'live_state' with all current messages.

    We run this test twice, once for polling and once for websocket.

    """
    # Prepare DB with some messages
    await Message.objects.acreate(title="Hello", message="World")
    await Message.objects.acreate(title="Foo", message="Bar")

    async with live_client(live_server_url, transport=transport) as (
        _sio,
        states,
        event,
    ):
        # Wait for initial live_state
        await wait_for_state(event)

        assert states, "Expected at least one live_state event"
        state = states[0]

        assert state["count"] == 2
        titles = {m["title"] for m in state["messages"]}
        assert titles == {"Hello", "Foo"}
