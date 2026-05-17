Routing
=======

``django-sio`` uses Django Channels routing. A Socket.IO endpoint must be
available for both HTTP and WebSocket scopes because Engine.IO supports both
HTTP long-polling and WebSocket transports.

Recommended endpoint
--------------------

The standard Socket.IO path is:

::

   /socket.io

In Channels routing this usually means matching ``^socket\.io/?$`` because the
path in the ASGI scope does not start with a leading slash.

Complete ASGI example
---------------------

.. code-block:: python

   import os

   from django.core.asgi import get_asgi_application
   from django.urls import re_path

   os.environ.setdefault("DJANGO_SETTINGS_MODULE", "your_project.settings")
   django_app = get_asgi_application()

   from channels.auth import AuthMiddlewareStack
   from channels.routing import ProtocolTypeRouter, URLRouter
   from channels.security.websocket import AllowedHostsOriginValidator

   from myapp.consumers import ChatConsumer

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
                       re_path("", django_app),
                   ]
               )
           ),
       }
   )

Why HTTP routing is required
----------------------------

Even if most clients upgrade to WebSocket, Socket.IO begins with Engine.IO
handshake semantics and may use HTTP long-polling. The HTTP route handles:

* initial polling handshakes;
* polling ``GET`` requests;
* polling ``POST`` payloads;
* clients that cannot or do not upgrade to WebSocket.

Why WebSocket routing is required
---------------------------------

The WebSocket route handles:

* direct WebSocket transport connections when the client chooses WebSocket;
* polling to WebSocket upgrades;
* Engine.IO heartbeat traffic over WebSocket;
* Socket.IO message frames once the WebSocket transport is established.

Middleware
----------

Use normal Channels middleware around the Socket.IO ASGI app. The common setup
is:

* ``AuthMiddlewareStack`` for Django session/user information in the ASGI scope;
* ``AllowedHostsOriginValidator`` around WebSocket routing to enforce allowed
  hosts/origins.

Fallback to Django HTTP
-----------------------

When routing HTTP, place the Socket.IO route before the normal Django ASGI
application fallback:

.. code-block:: python

   "http": AuthMiddlewareStack(
       URLRouter(
           [
               re_path(r"^socket\.io/?$", ChatConsumer.as_asgi()),
               re_path("", django_app),
           ]
       )
   )

If the fallback comes first, normal Django URL handling may receive Socket.IO
polling requests instead of ``django-sio``.
