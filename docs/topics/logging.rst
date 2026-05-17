Logging and debugging
=====================

All logging in ``django-sio`` goes through the standard Django logging
configuration and uses loggers under the ``"sio"`` namespace.

Logger names
------------

``sio.sio``
   Root package imports and version info.

``sio.engineio.*``
   Engine.IO transports, packets, and sessions.

``sio.socketio.*``
   Socket.IO protocol, server, namespaces, and sockets.

``sio.consumer``
   ``SocketIOConsumer`` wiring and event dispatch.

Enable debug logging
--------------------

Configure a ``"sio"`` logger in Django ``LOGGING`` settings:

.. code-block:: python

   LOGGING = {
       "version": 1,
       "disable_existing_loggers": False,
       "formatters": {
           "verbose_sio": {
               "format": (
                   "%(asctime)s [%(levelname)s] "
                   "%(name)s %(pathname)s:%(lineno)d %(funcName)s(): "
                   "%(message)s"
               ),
           },
       },
       "handlers": {
           "console_sio": {
               "class": "logging.StreamHandler",
               "formatter": "verbose_sio",
           },
       },
       "loggers": {
           "sio": {
               "handlers": ["console_sio"],
               "level": "DEBUG",   # DEBUG for full protocol tracing
               "propagate": False,
           },
       },
   }

What you will see
-----------------

At import time you will see messages such as:

* ``"sio root package imported"`` with ``version`` and ``socketio_version`` in
  ``extra``;
* ``"engineio package imported"`` with ``ENGINE_IO_VERSION``;
* ``"socketio package imported"`` with ``SOCKET_IO_VERSION``.

At ``DEBUG`` level you get detailed traces for:

* Engine.IO session lifecycle, including creation, destruction, and timeout;
* HTTP long-polling requests, including handshake, ``GET``, ``POST``, and
  payload sizes;
* WebSocket connect/upgrade and heartbeat pings/pongs;
* packet parsing and encoding for both Engine.IO and Socket.IO;
* room joins, room leaves, and room-based broadcasts;
* consumer wiring, connect hooks, disconnect hooks, event handlers, per-event
  dispatch, and whether handlers used acks.

Production logging
------------------

For production, keep the same handler and raise the level to ``INFO`` to only
see high-level lifecycle events:

.. code-block:: python

   "loggers": {
       "sio": {
           "handlers": ["console_sio"],
           "level": "INFO",
           "propagate": False,
       },
   }

You can send these logs to any Django-supported handler, including structured
JSON logging, files, or external log aggregators.
