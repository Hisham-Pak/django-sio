Consumer API reference
======================

``SocketIOConsumer``
--------------------

Import from ``sio``:

.. code-block:: python

   from sio import SocketIOConsumer

Subclass it to define a Socket.IO namespace consumer.

Attributes
~~~~~~~~~~

``namespace``
   Socket.IO namespace handled by the consumer. Defaults to ``"/"``.

Class methods
~~~~~~~~~~~~~

``as_asgi()``
   Returns an ASGI application suitable for Channels routing. The returned app
   routes HTTP scopes to the Engine.IO long-polling consumer and WebSocket
   scopes to the Engine.IO WebSocket consumer.

Lifecycle hooks
~~~~~~~~~~~~~~~

``async connect(self, socket, auth)``
   Optional. Called when a client connects to the consumer namespace.

   ``socket`` is a ``NamespaceSocket``. ``auth`` is the client authentication
   payload. Return ``True`` to accept the connection.

``async disconnect(self, socket, reason)``
   Optional. Called when a namespace socket disconnects.

Event handlers
~~~~~~~~~~~~~~

``async event_<name>(self, socket, *args, ack=None)``
   Optional. Handles the Socket.IO event named ``<name>``.

Example:

.. code-block:: python

   async def event_chat_message(self, socket, payload, ack=None):
       ...

This handles:

.. code-block:: javascript

   chat.emit("chat_message", { text: "Hello" });

Acknowledgement callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~

If the client sends an acknowledgement callback, the handler receives ``ack``.
Treat it as optional:

.. code-block:: python

   if ack is not None:
       await ack({"status": "ok"})
