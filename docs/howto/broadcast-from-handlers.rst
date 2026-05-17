Broadcast from event handlers
=============================

Socket.IO rooms let you send an event to a group of connected clients.

Join a room
-----------

Use ``socket.join`` inside ``connect`` or an event handler:

.. code-block:: python

   async def connect(self, socket, auth):
       await socket.join("lobby")
       return True

Leave a room
------------

Use ``socket.leave``:

.. code-block:: python

   async def event_leave_lobby(self, socket, ack=None):
       await socket.leave("lobby")
       if ack is not None:
           await ack({"status": "ok"})

Broadcast to a room
-------------------

Use ``socket.server.emit`` and include both ``room`` and ``namespace``:

.. code-block:: python

   async def event_chat_message(self, socket, payload, ack=None):
       await socket.server.emit(
           "chat_message",
           {"text": payload.get("text", "")},
           room="lobby",
           namespace=socket.namespace,
       )

       if ack is not None:
           await ack({"status": "ok"})

Why namespace matters
---------------------

Rooms belong to a Socket.IO namespace. Passing ``namespace=socket.namespace``
ensures the broadcast goes to sockets in the same namespace as the handler.

Broadcast only to the current client
------------------------------------

Use ``socket.emit`` for a message to the current namespace socket only:

.. code-block:: python

   await socket.emit("system_message", {"text": "Welcome!"})
