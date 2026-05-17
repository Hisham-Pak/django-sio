Protocol layers reference
=========================

``django-sio`` has three main layers above the ASGI server.

ASGI and Channels
-----------------

The ASGI server accepts HTTP and WebSocket connections. Django Channels routes
those scopes to the ASGI application returned by ``SocketIOConsumer.as_asgi()``.

Engine.IO
---------

Engine.IO provides transport-level behaviour:

* query parsing for ``EIO=4`` and ``transport=...``;
* HTTP long-polling;
* WebSocket transport;
* polling-to-WebSocket upgrade;
* ping/pong heartbeats;
* per-connection session state;
* packet and payload encoding.

Implemented in ``sio.engineio``.

Socket.IO
---------

Socket.IO provides application-level semantics:

* namespaces;
* events;
* acknowledgements;
* rooms;
* room broadcasts;
* packet parsing and encoding;
* binary attachment handling and placeholder substitution.

Implemented in ``sio.socketio``.

Consumer API
------------

The consumer API is the application-facing layer:

.. code-block:: python

   class ChatConsumer(SocketIOConsumer):
       namespace = "/chat"

       async def connect(self, socket, auth):
           return True

       async def event_chat_message(self, socket, payload, ack=None):
           ...

Most application code should stay at this layer.
