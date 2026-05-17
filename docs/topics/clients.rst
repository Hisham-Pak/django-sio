Clients
=======

``django-sio`` is designed to work with official Socket.IO clients, including
browser JavaScript, Node.js, and ``python-socketio``.

Browser JavaScript
------------------

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

Path and namespace
------------------

Do not confuse the Engine.IO path with the Socket.IO namespace.

``path: "/socket.io"``
   The HTTP/WebSocket endpoint routed in Django Channels.

``"/chat"``
   The Socket.IO namespace handled by your consumer.

A client can connect to the same server path and open one or more namespaces.

Transport selection
-------------------

Most clients can use both WebSocket and HTTP long-polling:

.. code-block:: javascript

   transports: ["websocket", "polling"]

Testing both transports is useful because they exercise different parts of the
Engine.IO layer.

Python client
-------------

The official Python client is useful for integration tests and scripts.

.. code-block:: python

   import asyncio
   import socketio

   async def main():
       client = socketio.AsyncClient()

       @client.on("chat_message", namespace="/chat")
       async def on_chat_message(payload):
           print("Chat:", payload)

       await client.connect(
           "http://localhost:8000",
           socketio_path="socket.io",
           namespaces=["/chat"],
           transports=["websocket", "polling"],
       )

       ack = await client.call(
           "chat_message",
           {"text": "Hello from Python"},
           namespace="/chat",
       )
       print("Ack:", ack)

       await client.disconnect()

   asyncio.run(main())

Authentication payloads
-----------------------

Socket.IO clients can pass an authentication payload while connecting to a
namespace. The server receives that payload as the ``auth`` argument to
``connect(self, socket, auth)``.

.. code-block:: javascript

   const socket = io("https://example.com", {
     path: "/socket.io",
     auth: { token: "client-token" },
   });

.. code-block:: python

   async def connect(self, socket, auth):
       token = (auth or {}).get("token")
       return True
