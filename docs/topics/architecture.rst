Architecture overview
=====================

At a lower level, request and message flow looks like this:

::

   ASGI → Channels → Engine.IO transport consumers
        → Engine.IO core → Socket.IO → your handlers

Conceptually, this matches the Node.js reference layering:

::

   Your code ↔ Socket.IO ↔ Engine.IO ↔ raw HTTP/WS

Transport flow
--------------

Concretely:

* the ASGI server, such as Daphne or Uvicorn, receives HTTP/WebSocket
  connections;
* Django Channels routes them to ``SocketIOConsumer.as_asgi()``;
* the consumer dispatches HTTP scopes to the Engine.IO long-polling transport;
* the consumer dispatches WebSocket scopes to the Engine.IO WebSocket transport;
* the Engine.IO core handles query parameters such as ``EIO=4`` and
  ``transport=...``;
* Engine.IO handles heartbeats, HTTP payload framing, WebSocket frames, and
  per-connection session state;
* completed Engine.IO ``message`` packets are passed to the Socket.IO layer;
* Socket.IO parses packets and calls your consumer event handlers.

Engine.IO layer
---------------

The Engine.IO implementation lives in ``sio.engineio`` and provides:

``EngineIOSession``
   Per-connection state, including transport, queues, and heartbeats.

``LongPollingConsumer``
   Channels ``AsyncHttpConsumer`` implementing the HTTP long-polling transport.

``EngineIOWebSocketConsumer``
   Channels ``AsyncWebsocketConsumer`` for the WebSocket transport and upgrade.

``EngineIOSocket``
   Application-facing wrapper around a session, used by Socket.IO.

``sio.engineio.packets``
   Helpers to encode and decode Engine.IO packets and HTTP payloads.

Each Engine.IO connection is represented by one ``EngineIOSession`` and one
``EngineIOSocket``. The polling and WebSocket transports share the same session.

Socket.IO layer
---------------

The Socket.IO implementation lives in ``sio.socketio`` and provides:

``SocketIOPacket``
   In-memory packet representation, including type, namespace, and data.

``SocketIOParser``
   Converts Engine.IO ``message`` payloads into Socket.IO packets, including
   binary attachment handling and placeholder substitution.

``SocketIOServer``
   Manages namespaces, per-namespace sockets, room membership, and broadcasts.

``NamespaceSocket``
   Represents one client in one namespace and exposes methods such as
   ``emit``, ``send``, ``join``, ``leave``, ``leave_all``, and ``disconnect``.

The server is configured once and used by all consumers. The singleton helper
``sio.socketio.server.get_socketio_server`` installs ``SocketIOServer`` as the
Engine.IO application handler through ``set_engineio_app``.

Consumer integration
--------------------

``sio.SocketIOConsumer`` glues everything together:

* it creates and configures the global ``SocketIOServer`` on first use;
* for each subclass, it registers a namespace;
* it wires ``connect`` and ``disconnect`` methods if present;
* it maps methods named ``event_<name>`` to Socket.IO events named ``<name>``;
* it exposes ``as_asgi()``, which returns an ASGI app that routes HTTP scopes to
  ``LongPollingConsumer`` and WebSocket scopes to ``EngineIOWebSocketConsumer``.

You typically never touch the lower-level Engine.IO consumers directly. Mount
your ``SocketIOConsumer`` subclass in Channels routing.
