from __future__ import annotations

import contextlib

import pytest
from sample_project.sampleapp.models import Message

from .helpers import (
    LIVE_NAMESPACE,
    live_client,
    reset_state_buffer,
    wait_for_state,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["polling", "websocket"])
async def test_create_action_broadcasts_state(
    live_server_url: str, transport: str
):
    """
    Emitting a 'live_action' with action='create' should:

    - create a DB row
    - trigger a new 'live_state' broadcast with the new count.

    """
    async with live_client(live_server_url, transport=transport) as (
        sio,
        states,
        event,
    ):
        # Try to consume initial state if any, but it's optional here
        with contextlib.suppress(TimeoutError):
            await wait_for_state(event)

        reset_state_buffer(states, event)

        # Emit create action
        await sio.emit(
            "live_action",
            {
                "action": "create",
                "title": "New Title",
                "message": "New Message",
            },
            namespace=LIVE_NAMESPACE,
        )

        # Wait for updated state
        await wait_for_state(event)

        assert states, "Expected at least one live_state event after create"
        state = states[-1]

        # DB should reflect new message (using async ORM helpers)
        assert await Message.objects.acount() == 1
        msg = await Message.objects.afirst()
        assert msg.title == "New Title"
        assert msg.message == "New Message"

        # State should match DB
        assert state["count"] == 1
        assert state["messages"][0]["title"] == "New Title"
        assert state["messages"][0]["message"] == "New Message"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["polling", "websocket"])
async def test_delete_action_broadcasts_state(
    live_server_url: str, transport: str
):
    """
    Emitting a 'live_action' with action='delete' should:

    - delete the DB row
    - trigger a new 'live_state' broadcast with the new count.

    """
    m1 = await Message.objects.acreate(title="One", message="First")
    m2 = await Message.objects.acreate(title="Two", message="Second")

    async with live_client(live_server_url, transport=transport) as (
        sio,
        states,
        event,
    ):
        # Initial broadcast (may or may not arrive, but we try)
        with contextlib.suppress(TimeoutError):
            await wait_for_state(event)

        reset_state_buffer(states, event)

        # Emit delete action
        await sio.emit(
            "live_action",
            {
                "action": "delete",
                "id": m1.id,
            },
            namespace=LIVE_NAMESPACE,
        )

        # Wait for updated state
        await wait_for_state(event)

        assert states, "Expected at least one live_state event after delete"
        state = states[-1]

        # DB should now only have the remaining message
        assert await Message.objects.acount() == 1
        remaining = await Message.objects.afirst()
        assert remaining.id == m2.id

        # State should reflect that
        assert state["count"] == 1
        ids = [m["id"] for m in state["messages"]]
        assert ids == [m2.id]
