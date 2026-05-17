Tutorial Part 3: Routing and browser client
===========================================

The Socket.IO endpoint receives both HTTP and WebSocket traffic. Route both
protocol types to the same ``ChatConsumer.as_asgi()`` application.

ASGI routing
------------

Edit ``config/asgi.py``:

.. code-block:: python

   # config/asgi.py
   import os

   from django.core.asgi import get_asgi_application
   from django.urls import re_path

   os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
   django_app = get_asgi_application()

   from channels.auth import AuthMiddlewareStack
   from channels.routing import ProtocolTypeRouter, URLRouter
   from channels.security.websocket import AllowedHostsOriginValidator

   from chat.consumers import ChatConsumer

   socketio_urlpatterns = [
       re_path(r"^socket\.io/?$", ChatConsumer.as_asgi()),
   ]

   application = ProtocolTypeRouter(
       {
           "websocket": AllowedHostsOriginValidator(
               AuthMiddlewareStack(URLRouter(socketio_urlpatterns))
           ),
           "http": AuthMiddlewareStack(
               URLRouter(
                   socketio_urlpatterns
                   + [
                       # Fallback: send all other HTTP requests to Django.
                       re_path("", django_app),
                   ]
               )
           ),
       }
   )

Run the server
--------------

Run the development server as usual:

.. code-block:: bash

   python manage.py runserver

Browser client
--------------

Use the official Socket.IO JavaScript client. This example connects to the
Socket.IO server at ``/socket.io`` and then opens the ``/chat`` namespace.

.. code-block:: html

   <!doctype html>
   <html>
     <head>
       <meta charset="utf-8" />
       <title>django-sio chat tutorial</title>
       <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
     </head>
     <body>
       <form id="form">
         <input id="message" autocomplete="off" placeholder="Type a message" />
         <button>Send</button>
       </form>
       <ul id="messages"></ul>

       <script>
         const managerSocket = io("http://localhost:8000", {
           path: "/socket.io",
           transports: ["websocket", "polling"],
         });

         const chat = managerSocket.io.socket("/chat");

         const messages = document.getElementById("messages");
         const form = document.getElementById("form");
         const input = document.getElementById("message");

         function addMessage(text) {
           const item = document.createElement("li");
           item.textContent = text;
           messages.appendChild(item);
         }

         chat.on("connect", () => {
           addMessage("Connected to /chat");
         });

         chat.on("system_message", (payload) => {
           addMessage(`System: ${payload.text}`);
         });

         chat.on("chat_message", (payload) => {
           addMessage(`Chat: ${payload.text}`);
         });

         form.addEventListener("submit", (event) => {
           event.preventDefault();
           const text = input.value;
           input.value = "";

           chat.emit("chat_message", { text }, (ack) => {
             console.log("Ack:", ack);
           });
         });
       </script>
     </body>
   </html>

A compact browser example
-------------------------

The same idea can be written without the surrounding HTML:

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

In the next part you expand the consumer with room events and acks.
