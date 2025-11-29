import logging
from channels.db import database_sync_to_async

from sio import SocketIOConsumer

from .models import Message


logger = logging.getLogger("sample_project.config")


class LiveMessageConsumer(SocketIOConsumer):
    """
    Socket.IO version of the live message consumer.

    - All clients join the "live_message" room on connect.
    - Clients send a "live_action" event with a payload:
        { "action": "create", "title": "...", "message": "..." }
        or
        { "action": "delete", "id": <msg_id> }
    - After any change, the current state is broadcast to the room as
      a "live_state" event.

    """

    # Socket.IO namespace (you can keep "/" if you want)
    namespace = "/live"

    # ------------------------------------------------------------------ #
    # Connect / disconnect
    # ------------------------------------------------------------------ #

    async def connect(self, socket, auth):
        """
        Called when the client sends a Socket.IO CONNECT for this namespace. On
        connect, join the live_message room and send the current state.

        Return True to accept, False to reject.

        """
        # Test-only: echo auth so the JS test suite can verify it flows through.
        # (No-op for normal clients that ignore this event.)
        await socket.emit("auth_echo", auth or {})

        # Put this socket into a logical room called "live_message"
        await socket.join("live_message")

        # Send the current state only to this client
        await self._send_current_state_to_socket(socket)
        return True  # accept

    async def disconnect(self, socket, reason):
        """
        Called when this Socket.IO socket is being disconnected.

        Rooms are already cleaned up by the server.

        """
        # Optional: log or cleanup
        # print("LiveMessage disconnect:", socket.id, reason)
        pass

    # ------------------------------------------------------------------ #
    # Socket.IO event handler
    # ------------------------------------------------------------------ #

    async def event_live_action(self, socket, payload, ack=None):
        """
        Handle incoming actions from the client.

        Expected payload:
            { "action": "create", "title": "...", "message": "..." }
            or
            { "action": "delete", "id": <msg_id> }

        """
        action = payload.get("action", "create")

        if action == "create":
            title = payload.get("title", "")
            text = payload.get("message", "")
            await self._create_message(title=title, text=text)

        elif action == "delete":
            msg_id = payload.get("id")
            await self._delete_message(msg_id)

        # After any action, broadcast current state to everyone in the room
        await self._broadcast_current_state(socket)

        # Optional: send an ack back to the caller
        if ack is not None:
            await ack({"status": "ok"})


    # ------------------------------------------------------------------ #
    # Test helper events for JS client coverage
    # ------------------------------------------------------------------ #

    async def event_echo(self, socket, payload, ack=None):
        """
        Simple echo roundtrip:
        - emits "echo" with the same payload back to the caller
        - optionally acks with {"status": "ok", "echo": payload}
        """
        await socket.emit("echo", payload)
        if ack is not None:
            await ack({"status": "ok", "echo": payload})

    async def event_ack_only(self, socket, payload, ack=None):
        """
        Only sends an ack, no server-side emit. Useful to test pure ack flows.
        """
        if ack is not None:
            await ack({"status": "ok", "payload": payload})

    async def event_join_room(self, socket, payload, ack=None):
        """
        Join an arbitrary room provided by the client.
        payload: { "room": "name" }
        """
        room = payload.get("room")
        if room:
            await socket.join(room)
        if ack is not None:
            await ack({"status": "ok", "room": room})

    async def event_leave_room(self, socket, payload, ack=None):
        """
        Leave an arbitrary room.
        payload: { "room": "name" }
        """
        room = payload.get("room")
        if room:
            await socket.leave(room)
        if ack is not None:
            await ack({"status": "ok", "room": room})

    async def event_room_broadcast(self, socket, payload, ack=None):
        """
        Broadcast a payload to everyone in a named room.
        payload: { "room": "name", "data": <any JSON-serializable> }
        """
        room = payload.get("room")
        data = payload.get("data")
        await socket.server.emit(
            "room_broadcast",
            data,
            room=room,
            namespace=socket.namespace,
        )
        if ack is not None:
            await ack({"status": "ok"})

    async def event_trigger_error(self, socket, payload, ack=None):
        """
        Deliberately simulate raise an error to ensure the server doesn’t
        explode and the client doesn’t hang forever waiting for an ack.

        Expected payload:
            { "message": "some error text" }
        """
        message = payload.get("message", "forced error from trigger_error")
        try:
            # Do something "bad" to exercise error logic
            raise RuntimeError(message)
        except Exception as exc:
            # Swallow the exception so Channels doesn't log "Exception inside application"
            logger.debug("Swallowed expected test error in trigger_error: %s", exc)
            if ack is not None:
                await ack({"status": "error", "message": str(exc)})

    # ------------------------------------------------------------------ #
    # State sending helpers
    # ------------------------------------------------------------------ #

    async def _send_current_state_to_socket(self, socket):
        """
        Send the current message state only to this socket.
        """
        state = await self._fetch_state()
        await socket.emit("live_state", state)

    async def _broadcast_current_state(self, socket):
        """
        Broadcast current state to everyone in the "live_message" room.
        """
        state = await self._fetch_state()
        await socket.server.emit(
            "live_state",
            state,
            room="live_message",
            namespace=socket.namespace,
        )

    # ------------------------------------------------------------------ #
    # DB helpers
    # ------------------------------------------------------------------ #

    @database_sync_to_async
    def _fetch_state(self):
        qs = Message.objects.order_by("-created")
        count = qs.count()
        messages = list(qs.values("id", "title", "message"))
        return {"count": count, "messages": messages}


    @database_sync_to_async
    def _create_message(self, title, text):
        Message.objects.create(title=title, message=text)

    @database_sync_to_async
    def _delete_message(self, msg_id):
        if msg_id is not None:
            Message.objects.filter(id=msg_id).delete()
