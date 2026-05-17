Tutorial Part 2: Write a chat consumer
======================================

Create ``chat/consumers.py`` and define a Socket.IO consumer.

.. code-block:: python

   # chat/consumers.py
   from sio import SocketIOConsumer

   class ChatConsumer(SocketIOConsumer):
       namespace = "/chat"

       async def connect(self, socket, auth):
           # Put this client into a logical room.
           await socket.join("lobby")

           # Send an initial message only to this client.
           await socket.emit("system_message", {"text": "Welcome!"})

           # Return True to accept the Socket.IO namespace connection.
           return True

       async def disconnect(self, socket, reason):
           # Optional cleanup can go here.
           pass

       async def event_chat_message(self, socket, payload, ack=None):
           text = payload.get("text", "")

           # Broadcast to everyone in the room.
           await socket.server.emit(
               "chat_message",
               {"text": text},
               room="lobby",
               namespace=socket.namespace,
           )

           # Optional ack back to the caller.
           if ack is not None:
               await ack({"status": "ok"})

What each method does
---------------------

``namespace = "/chat"``
   Registers this consumer for the Socket.IO namespace named ``/chat``.

``connect(self, socket, auth)``
   Runs when the client connects to the namespace. The ``auth`` argument is the
   authentication payload sent by the Socket.IO client. Return ``True`` to
   accept the connection.

``disconnect(self, socket, reason)``
   Runs when the namespace socket disconnects. Use it for optional cleanup.

``event_chat_message(self, socket, payload, ack=None)``
   Handles the Socket.IO event named ``chat_message``. Any method named
   ``event_<name>`` becomes the handler for the event named ``<name>``.

The ``socket`` object
---------------------

The ``socket`` argument represents this connected client in this namespace. In
this tutorial you use it to:

* join the ``lobby`` room with ``socket.join("lobby")``;
* emit to the current client with ``socket.emit(...)``;
* broadcast through the server with ``socket.server.emit(...)``;
* keep broadcasts scoped to the current namespace with ``namespace=socket.namespace``.

In the next part you mount this consumer in ASGI routing and connect a browser
client.
