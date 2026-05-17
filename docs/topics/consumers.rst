Consumers
=========

The ``sio.SocketIOConsumer`` class is the primary API most applications use.
It glues the Engine.IO and Socket.IO layers to Django Channels and exposes a
small class-based interface.

Basic layout
------------

.. code-block:: python

   from sio import SocketIOConsumer

   class ChatConsumer(SocketIOConsumer):
       namespace = "/chat"

       async def connect(self, socket, auth):
           return True

       async def disconnect(self, socket, reason):
           pass

       async def event_chat_message(self, socket, payload, ack=None):
           pass

A consumer subclass can define:

``namespace``
   The Socket.IO namespace handled by this consumer. It defaults to ``"/"``.

``connect(self, socket, auth)``
   Optional lifecycle hook for namespace connections.

``disconnect(self, socket, reason)``
   Optional lifecycle hook for namespace disconnects.

``event_<name>(self, socket, *args, ack=None)``
   Optional event handlers. ``event_chat_message`` handles
   ``"chat_message"``.

Connection handling
-------------------

The connect hook receives a namespace socket and the client authentication
payload:

.. code-block:: python

   async def connect(self, socket, auth):
       await socket.join("lobby")
       await socket.emit("system_message", {"text": "Welcome!"})
       return True

Return ``True`` to accept the namespace connection. If your application needs to
reject a connection, perform your checks in this method and return a falsey
value according to the behaviour supported by your version of ``django-sio``.

Disconnect handling
-------------------

The disconnect hook receives the namespace socket and a reason:

.. code-block:: python

   async def disconnect(self, socket, reason):
       # Optional cleanup.
       pass

Use this for application-level cleanup. Room cleanup for the socket itself is
handled by the Socket.IO server layer.

Event handlers
--------------

Any method named ``event_<name>`` becomes a Socket.IO event handler for
``"<name>"`` in that namespace.

.. code-block:: python

   async def event_chat_message(self, socket, payload, ack=None):
       text = payload.get("text", "")
       await socket.server.emit(
           "chat_message",
           {"text": text},
           room="lobby",
           namespace=socket.namespace,
       )
       if ack is not None:
           await ack({"status": "ok"})

Event arguments
---------------

Socket.IO events can carry one or more arguments. ``django-sio`` passes those
arguments positionally after ``socket``. For simple JSON events, a single
``payload`` dictionary is common.

.. code-block:: python

   async def event_update_state(self, socket, payload, ack=None):
       ...

For multi-argument events, accept multiple positional arguments:

.. code-block:: python

   async def event_move(self, socket, x, y, ack=None):
       ...

Acknowledgements
----------------

If the client provides an acknowledgement callback, the handler receives it as
``ack``. It is optional.

.. code-block:: python

   if ack is not None:
       await ack({"status": "ok"})

Consumer registration
---------------------

For each subclass, ``SocketIOConsumer``:

* creates and configures the global ``SocketIOServer`` on first use;
* registers the namespace declared by ``namespace``;
* wires ``connect`` and ``disconnect`` methods if present;
* maps ``event_<name>`` methods to Socket.IO events.

You typically do not instantiate consumers yourself. Mount them in Channels
routing with ``ChatConsumer.as_asgi()``.
