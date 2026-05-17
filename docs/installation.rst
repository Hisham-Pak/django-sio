Installation
============

Install the package
-------------------

Install, once published, with:

.. code-block:: bash

   pip install django-sio

Install Django Channels and an ASGI server suitable for your project. For a
Daphne-based setup, include ``daphne`` and ``channels`` in your environment and
Django settings.

Django settings
---------------

Add Channels to ``INSTALLED_APPS`` and point Django at your ASGI application:

.. code-block:: python

   INSTALLED_APPS = [
       "daphne",          # or use uvicorn or another ASGI server outside INSTALLED_APPS
       # ...
       "channels",
       "myapp",
   ]

   ASGI_APPLICATION = "your_project.config.asgi.application"

Configure a channel layer for Socket.IO room broadcasting. An in-memory layer is
fine for local development and tests:

.. code-block:: python

   CHANNEL_LAYERS = {
       "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
   }

For production, use a process-safe backend such as Redis for the Channels
channel layer. Remember that the channel layer is for room broadcasting; it does
not store Engine.IO sessions. See :doc:`topics/deployment` before running
multiple workers.

ASGI routing
------------

The Socket.IO endpoint must be routed for both HTTP and WebSocket scopes. The
quickstart route is usually ``/socket.io``:

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

Next steps
----------

After installation, follow :doc:`tutorial/index` to build a small chat app, or
read :doc:`topics/consumers` if you already know what namespace and event
handlers you need.