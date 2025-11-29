from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

import socketio

LIVE_NAMESPACE = "/live"
SOCKETIO_PATH = "socket.io"
STATE_TIMEOUT = 1.0


@asynccontextmanager
async def live_client(
    base_url: str,
    transport: str,
) -> AsyncIterator[
    tuple[socketio.AsyncClient, list[dict[str, Any]], asyncio.Event]
]:
    """
    Connect a python-socketio AsyncClient to the /live namespace and collect
    'live_state' events.

    transport: "polling" or "websocket"
    Yields: (sio_client, received_states, state_event)

    """
    if transport not in {"polling", "websocket"}:
        raise ValueError(f"Unsupported transport: {transport!r}")

    sio = socketio.AsyncClient()
    received_states: list[dict[str, Any]] = []
    state_event = asyncio.Event()

    @sio.on("live_state", namespace=LIVE_NAMESPACE)
    async def on_live_state(data: dict[str, Any]):
        received_states.append(data)
        state_event.set()

    connect_kwargs: dict[str, Any] = {
        "socketio_path": SOCKETIO_PATH,
        "namespaces": [LIVE_NAMESPACE],
        "transports": [transport],  # force specific transport
        "wait_timeout": STATE_TIMEOUT,
    }

    await sio.connect(base_url, **connect_kwargs)

    try:
        yield sio, received_states, state_event
    finally:
        # Try a normal disconnect, but don't let it hang the tests.
        try:
            await asyncio.wait_for(sio.disconnect(), timeout=STATE_TIMEOUT)
        except TimeoutError:
            # Fallback: force abort on the engineio client
            with suppress(Exception):
                await sio.eio.disconnect(abort=True)


async def wait_for_state(
    event: asyncio.Event, timeout: float = STATE_TIMEOUT
) -> None:
    """
    Wait for a single live_state event with timeout.
    """
    await asyncio.wait_for(event.wait(), timeout=timeout)


def reset_state_buffer(states: list[Any], event: asyncio.Event) -> None:
    """
    Clear collected states and reset the event for the next wait.
    """
    states.clear()
    event.clear()
