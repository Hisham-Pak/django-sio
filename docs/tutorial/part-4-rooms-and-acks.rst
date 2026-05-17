Tutorial Part 4: Rooms and acknowledgements
===========================================

The first consumer always joins every client to ``lobby``. This part adds
explicit events for joining and leaving rooms.

Update the consumer
-------------------

.. code-block:: python

   # chat/consumers.py
   from sio import SocketIOConsumer

   class ChatConsumer(SocketIOConsumer):
       namespace = "/chat"

       async def connect(self, socket, auth):
           await socket.join("lobby")
           await socket.emit("system_message", {"text": "Welcome!"})
           return True

       async def disconnect(self, socket, reason):
           pass

       async def event_join_room(self, socket, payload, ack=None):
           room = payload.get("room") or "lobby"
           await socket.join(room)

           if ack is not None:
               await ack({"status": "ok", "room": room})

       async def event_leave_room(self, socket, payload, ack=None):
           room = payload.get("room") or "lobby"
           await socket.leave(room)

           if ack is not None:
               await ack({"status": "ok", "room": room})

       async def event_chat_message(self, socket, payload, ack=None):
           room = payload.get("room") or "lobby"
           text = payload.get("text", "")

           await socket.server.emit(
               "chat_message",
               {"room": room, "text": text},
               room=room,
               namespace=socket.namespace,
           )

           if ack is not None:
               await ack({"status": "ok", "room": room})

Use the new events from JavaScript
----------------------------------

.. code-block:: javascript

   chat.emit("join_room", { room: "lobby" }, (ack) => {
     console.log("Joined:", ack);
   });

   chat.emit("chat_message", { room: "lobby", text: "Hello room" }, (ack) => {
     console.log("Message ack:", ack);
   });

   chat.emit("leave_room", { room: "lobby" }, (ack) => {
     console.log("Left:", ack);
   });

How acks work
-------------

When a Socket.IO client sends an event with a callback, ``django-sio`` exposes
that callback as ``ack`` in your event handler.

.. code-block:: python

   async def event_example(self, socket, payload, ack=None):
       if ack is not None:
           await ack({"status": "ok"})

Always treat ``ack`` as optional. Clients are allowed to emit events without a
callback.

Broadcasting to a room
----------------------

Use ``socket.server.emit`` for room broadcasts:

.. code-block:: python

   await socket.server.emit(
       "chat_message",
       {"text": "Hello"},
       room="lobby",
       namespace=socket.namespace,
   )

The ``namespace`` argument matters. It keeps the event inside the Socket.IO
namespace where the room membership exists.
