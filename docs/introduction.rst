Introduction
============

``django-sio`` lets a Django project speak Socket.IO while still using Django
Channels for ASGI routing, HTTP handling, WebSocket handling, and channel-layer
broadcasts.

You write application code against Socket.IO concepts:

* namespaces such as ``"/"`` and ``"/chat"``;
* rooms such as ``"lobby"``;
* events such as ``"chat_message"`` and ``"live_state"``;
* acknowledgements, often called acks, where the client passes a callback and
  the server calls it after processing an event.

Everything below that application layer is handled for you:

* HTTP versus WebSocket transport selection;
* Engine.IO ping/pong and heartbeats;
* HTTP long-polling to WebSocket upgrade;
* Engine.IO packet framing;
* Socket.IO packet parsing;
* room broadcasting through the Channels channel layer.

Mental model
------------

If you are used to Node.js Socket.IO, you can think of this package as:

::

   Your Django code ↔ Socket.IO ↔ Engine.IO ↔ raw HTTP/WebSocket

You stay on the left-hand side. You create a consumer, define lifecycle hooks,
write event handlers, join rooms, leave rooms, and emit events.

A single client connection has two layers of identity:

* an Engine.IO session, which owns the transport connection and heartbeat state;
* one or more Socket.IO namespace sockets, which represent the application-level
  Socket.IO connection for each namespace.

For most application code you only interact with the namespace socket passed to
your consumer methods.

Where Channels fits
-------------------

Django Channels is responsible for accepting ASGI scopes and dispatching them to
consumers. ``django-sio`` exposes one ASGI application through
``SocketIOConsumer.as_asgi()`` and that application handles both:

* HTTP scopes, used by the Engine.IO long-polling transport; and
* WebSocket scopes, used by the Engine.IO WebSocket transport.

The same Socket.IO endpoint must therefore be routed for both HTTP and
WebSocket traffic.

What you normally write
-----------------------

A typical application has one or more subclasses of ``sio.SocketIOConsumer``.
Each subclass declares a namespace and methods for connection lifecycle events
and Socket.IO events.

.. code-block:: python

   from sio import SocketIOConsumer

   class ChatConsumer(SocketIOConsumer):
       namespace = "/chat"

       async def connect(self, socket, auth):
           await socket.join("lobby")
           await socket.emit("system_message", {"text": "Welcome!"})
           return True

       async def disconnect(self, socket, reason):
           pass

       async def event_chat_message(self, socket, payload, ack=None):
           await socket.server.emit(
               "chat_message",
               payload,
               room="lobby",
               namespace=socket.namespace,
           )

           if ack is not None:
               await ack({"status": "ok"})

Any method named ``event_<name>`` handles the Socket.IO event named
``"<name>"`` for that consumer's namespace.

What this project is not
------------------------

``django-sio`` does not replace Django Channels. It builds on Channels.

It also does not turn the Channels channel layer into shared Engine.IO session
storage. The current Engine.IO session registry is in-process, so deployments
with multiple workers need sticky sessions. See :doc:`topics/deployment` for the
full production caveat.
