=========================
django-sio
=========================

Socket.IO for Django, powered by Channels and compatible with the official
Socket.IO clients.

``django-sio`` implements the Socket.IO v5 protocol on top of an in-process
Engine.IO v4 server, using Django Channels for HTTP/WebSocket handling and
broadcasts.

It is designed to work with the official Socket.IO clients
(browser JS, Node.js, python-socketio, etc.).


Beginner guide
==============

What this gives you
-------------------

* A **Socket.IO server** running inside Django/Channels.
* Support for both **WebSocket and HTTP long-polling**.
* A simple, class-based **consumer API**:

  * ``connect(self, socket, auth)``
  * ``disconnect(self, socket, reason)``
  * ``event_<name>(self, socket, *args, ack=None)``

If you already know Socket.IO from Node.js, this behaves very similarly on the
server side, but lives inside your Django project.


Installation
------------

Install (once published) with:

.. code-block:: bash

   pip install django-sio

In your Django settings:

.. code-block:: python

   INSTALLED_APPS = [
       # ...
       "channels",
       "sio",  # django-sio
   ]

   ASGI_APPLICATION = "your_project.config.asgi.application"

Configure a channel layer (Redis or in-memory) as documented in Channels, for
room broadcasting:

.. code-block:: python

   CHANNEL_LAYERS = {
       "default": {
           "BACKEND": "channels_redis.core.RedisChannelLayer",
           "CONFIG": {
               "hosts": [("127.0.0.1", 6379)],
           },
       },
   }


Quickstart
----------

1. Define a Socket.IO consumer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a subclass of :class:`sio.SocketIOConsumer` and implement the lifecycle
and event handlers you need:

.. code-block:: python

   # myapp/consumers.py
   from sio import SocketIOConsumer

   class ChatConsumer(SocketIOConsumer):
       namespace = "/chat"

       async def connect(self, socket, auth):
           # Put this client into a logical room
           await socket.join("lobby")

           # Send an initial message only to this client
           await socket.emit("system_message", {"text": "Welcome!"})
           return True  # accept the connection

       async def disconnect(self, socket, reason):
           # Optional cleanup
           pass

       async def event_chat_message(self, socket, payload, ack=None):
           text = payload.get("text", "")

           # Broadcast to everyone in the room
           await socket.server.emit(
               "chat_message",
               {"text": text},
               room="lobby",
               namespace=socket.namespace,
           )

           # Optional ack back to caller
           if ack is not None:
               await ack({"status": "ok"})

Any method named ``event_<name>`` becomes the handler for the Socket.IO event
``"<name>"`` in that namespace. In this example,
``event_chat_message`` handles the event ``"chat_message"``.


2. Wire it in ASGI routing
~~~~~~~~~~~~~~~~~~~~~~~~~~

Route both HTTP and WebSocket traffic for the Socket.IO path to your consumer:

.. code-block:: python

   # your_project/config.asgi.py
   import os

   from django.core.asgi import get_asgi_application
   from django.urls import re_path

   os.environ.setdefault("DJANGO_SETTINGS_MODULE", "your_project.settings")
   django_app = get_asgi_application()

   from channels.auth import AuthMiddlewareStack
   from channels.routing import ProtocolTypeRouter, URLRouter
   from channels.security.websocket import AllowedHostsOriginValidator

   from myapp.consumers import ChatConsumer

   application = ProtocolTypeRouter(
       {
           "websocket": AllowedHostsOriginValidator(
               AuthMiddlewareStack(
                   URLRouter(
                       [
                           re_path(r"^socket\.io/?$", ChatConsumer.as_asgi()),
                       ]
                   )
               )
           ),
           "http": AuthMiddlewareStack(
               URLRouter(
                   [
                       re_path(r"^socket\.io/?$", ChatConsumer.as_asgi()),
                       # Fallback: send all other HTTP to Django
                       re_path("", django_app),
                   ]
               )
           ),
       }
   )


3. Connect from a client
~~~~~~~~~~~~~~~~~~~~~~~~

Browser example using the official JS client:

.. code-block:: javascript

   const socket = io("https://example.com", {
     path: "/socket.io",
     transports: ["websocket", "polling"],
   });

   const chat = socket.io.socket("/chat");

   chat.on("connect", () => {
     console.log("Connected to /chat");
   });

   chat.on("system_message", (payload) => {
     console.log("System:", payload.text);
   });

   chat.on("chat_message", (payload) => {
     console.log("Chat:", payload.text);
   });

   chat.emit("chat_message", { text: "Hello" }, (ack) => {
     console.log("Ack:", ack);
   });


Mental model (for beginners)
----------------------------

You write application code against **Socket.IO semantics**:

* namespaces (``"/"``, ``"/chat"``, etc.)
* rooms (``socket.join("room")`` / ``socket.leave("room")``)
* events (``"chat_message"``, ``"live_state"``, etc.)
* acks (callbacks after an event is processed)

Everything else is handled for you:

* HTTP vs WebSocket,
* Engine.IO ping/pong and heartbeats,
* polling → WebSocket upgrade,
* room broadcasting via the Channels channel layer.

If you’re used to Node.js Socket.IO, you can think of this package as:

::

   Your Django code ↔ Socket.IO ↔ Engine.IO ↔ raw HTTP/WebSocket

You stay on the left-hand side.


Advanced concepts
=================

Configuration
-------------

Engine.IO timing and payload limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, the Engine.IO layer uses conservative defaults for heartbeats and
HTTP payload limits. These can be overridden globally via Django settings.

The following settings are supported:

* ``SIO_ENGINEIO_PING_INTERVAL_MS``

  Interval (in milliseconds) between server → client pings.

  Default: ``25_000`` (25 seconds)

* ``SIO_ENGINEIO_PING_TIMEOUT_MS``

  Time (in milliseconds) the server waits for a pong after sending a ping
  before considering the connection dead.

  Default: ``20_000`` (20 seconds)

* ``SIO_ENGINEIO_MAX_PAYLOAD_BYTES``

  Maximum size (in bytes) of a single HTTP long-polling payload. Engine.IO
  packets queued for polling are batched up to this limit; any segments that
  do not fit are delivered in a subsequent response.

  Default: ``1_000_000`` (1 MB)

Example configuration in ``settings.py``:

.. code-block:: python

   # Engine.IO timing / payload tuning (optional)
   SIO_ENGINEIO_PING_INTERVAL_MS = 25_000      # default 25_000
   SIO_ENGINEIO_PING_TIMEOUT_MS = 20_000       # default 20_000
   SIO_ENGINEIO_MAX_PAYLOAD_BYTES = 1_000_000  # default 1_000_000

These values are read once at import time by the Engine.IO implementation and
are used consistently across:

* the Engine.IO "open" packet sent to clients (``pingInterval``,
  ``pingTimeout``, ``maxPayload`` fields),
* the HTTP long-polling timeout and batching,
* the WebSocket heartbeat loop.

They are **global** settings for the entire process; per-session overrides are
not currently supported.

For most applications you do not need to touch these. You may want to lower
the ping interval/timeout for latency-sensitive apps, or increase
``SIO_ENGINEIO_MAX_PAYLOAD_BYTES`` if you know you will be sending larger
messages over HTTP long-polling and are comfortable with the trade-off in
request size vs. frequency.


Architecture overview
---------------------

At a lower level, the data flow for a request/response looks like this:

*Transport-wise*:

::

   ASGI → Channels → Engine.IO transport consumers
        → Engine.IO core → Socket.IO → your handlers

Concretely:

* The ASGI server (daphne/uvicorn/etc.) receives HTTP/WebSocket connections.
* Django Channels routes them to your ``SocketIOConsumer.as_asgi()``.
* The consumer dispatches:
  * HTTP scopes to the Engine.IO long-polling transport, and
  * WebSocket scopes to the Engine.IO WebSocket transport.
* The Engine.IO core handles:
  * query parameters (``EIO=4``, ``transport=...``),
  * heartbeats (ping/pong),
  * HTTP payload framing and WebSocket frames,
  * per-connection session state.
* Completed Engine.IO "message" packets are passed to the Socket.IO layer,
  which parses Socket.IO packets and calls your event handlers.

Conceptually, this matches the Node.js reference layering:

::

   Your code ↔ Socket.IO ↔ Engine.IO ↔ raw HTTP/WS


Engine.IO layer
---------------

The Engine.IO implementation lives in ``sio.engineio`` and provides:

* ``EngineIOSession`` – per-connection state (transport, queues, heartbeats).
* ``LongPollingConsumer`` – Channels ``AsyncHttpConsumer`` implementing the
  HTTP long-polling transport.
* ``EngineIOWebSocketConsumer`` – Channels ``AsyncWebsocketConsumer`` for
  the WebSocket transport and upgrade.
* ``EngineIOSocket`` – application-facing wrapper around a session, used by
  Socket.IO.
* Helpers in ``sio.engineio.packets`` to encode/decode Engine.IO packets and
  HTTP payloads.

Each Engine.IO connection is represented by one ``EngineIOSession`` and one
``EngineIOSocket``. The transports (polling / websocket) share the session.


Socket.IO layer
---------------

The Socket.IO implementation lives in ``sio.socketio`` and provides:

* ``SocketIOPacket`` – in-memory packet representation (type, namespace, data).
* ``SocketIOParser`` – converts Engine.IO "message" payloads into Socket.IO
  packets, including binary attachment handling and placeholder substitution.
* ``SocketIOServer`` – manages:

  * namespaces,
  * per-namespace sockets,
  * room membership and broadcasts.

* ``NamespaceSocket`` – represents one client in one namespace, with methods:

  * ``emit`` / ``send``
  * ``join`` / ``leave`` / ``leave_all``
  * ``disconnect``

The server is configured once and used by all consumers. There is a singleton
helper :func:`sio.socketio.server.get_socketio_server` that installs
``SocketIOServer`` as the Engine.IO application handler (via
``set_engineio_app``).


Consumer integration
--------------------

The :class:`sio.SocketIOConsumer` class glues everything together:

* It creates (on first use) and configures the global ``SocketIOServer``.
* For each subclass:

  * registers a namespace (``namespace`` attribute, defaults to ``"/"``),
  * wires ``connect`` and ``disconnect`` methods if present,
  * maps methods named ``event_<name>`` to Socket.IO events named ``"<name>"``.

* It exposes ``as_asgi()`` which returns an ASGI app that:

  * routes HTTP scopes to ``LongPollingConsumer``,
  * routes WebSocket scopes to ``EngineIOWebSocketConsumer``.

You typically never touch the lower-level Engine.IO consumers directly; you
just mount your ``SocketIOConsumer`` subclass in Channels routing.


Deployment and scaling
----------------------

The default Engine.IO session registry is **in-memory and single-process**.

That means:

* All Engine.IO sessions (polling & WebSocket) are stored in the Python
  process that accepted the initial connection.
* If you run multiple worker processes or multiple containers behind a load
  balancer **without sticky sessions**, requests for the same client may hit a
  different process, and the Engine.IO ``sid`` will not be found.

In production you MUST either:

* run a single ASGI worker process, or
* configure your load balancer to use **sticky sessions** (also known as
  "session affinity") so that all requests for a given client always reach the
  same process.

The Channels channel layer (e.g. Redis) is used only for **Socket.IO room
broadcasting**; it does not provide shared storage for Engine.IO sessions.

A future version may expose a pluggable session registry interface for more
advanced deployments, but the current design assumes in-process sessions.


Testing and development
-----------------------

The repository includes:

* **Unit tests** for:

  * Engine.IO packet/session logic.
  * Socket.IO encoding/decoding and parser behaviour.
  * Namespace and room handling.
  * Consumer wiring and disconnect hooks.

* **Integration tests** using a real Channels live server and a
  ``python-socketio.AsyncClient`` that talk to the example app in
  ``tests/sample_project`` and exercise both polling and WebSocket transports.

Run tests with:

.. code-block:: bash

   pytest

You can use coverage tools (``pytest-cov``, ``coverage.py``) to inspect
branch coverage and verify that all protocol branches are exercised during
testing.
