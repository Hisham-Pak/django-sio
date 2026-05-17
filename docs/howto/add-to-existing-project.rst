Add django-sio to an existing Django project
============================================

This guide shows the minimal changes needed to add Socket.IO to a project that
already has normal Django views.

1. Install dependencies
-----------------------

.. code-block:: bash

   pip install django-sio

2. Enable Channels
------------------

In settings:

.. code-block:: python

   INSTALLED_APPS = [
       "daphne",
       # ... existing apps ...
       "channels",
       "myapp",
   ]

   ASGI_APPLICATION = "your_project.config.asgi.application"

   CHANNEL_LAYERS = {
       "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
   }

Use Redis or another process-safe channel layer for production broadcasting.

3. Add a consumer
-----------------

.. code-block:: python

   from sio import SocketIOConsumer

   class NotificationsConsumer(SocketIOConsumer):
       namespace = "/notifications"

       async def connect(self, socket, auth):
           await socket.join("notifications")
           return True

       async def event_ping(self, socket, payload, ack=None):
           if ack is not None:
               await ack({"status": "ok"})

4. Route Socket.IO before Django HTTP fallback
----------------------------------------------

.. code-block:: python

   import os

   from django.core.asgi import get_asgi_application
   from django.urls import re_path

   os.environ.setdefault("DJANGO_SETTINGS_MODULE", "your_project.settings")
   django_app = get_asgi_application()

   from channels.auth import AuthMiddlewareStack
   from channels.routing import ProtocolTypeRouter, URLRouter
   from channels.security.websocket import AllowedHostsOriginValidator

   from myapp.consumers import NotificationsConsumer

   socketio_patterns = [
       re_path(r"^socket\.io/?$", NotificationsConsumer.as_asgi()),
   ]

   application = ProtocolTypeRouter(
       {
           "websocket": AllowedHostsOriginValidator(
               AuthMiddlewareStack(URLRouter(socketio_patterns))
           ),
           "http": AuthMiddlewareStack(
               URLRouter(socketio_patterns + [re_path("", django_app)])
           ),
       }
   )

5. Connect a client
-------------------

.. code-block:: javascript

   const socket = io("https://example.com", {
     path: "/socket.io",
     transports: ["websocket", "polling"],
   });

   const notifications = socket.io.socket("/notifications");

   notifications.emit("ping", {}, (ack) => {
     console.log(ack);
   });
