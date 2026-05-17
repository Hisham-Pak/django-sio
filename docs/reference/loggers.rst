Loggers reference
=================

``django-sio`` uses the standard Python and Django logging system.

Logger hierarchy
----------------

``sio``
   Parent logger for all package logs. Configure this logger to affect all
   package logging.

``sio.sio``
   Root package imports and version info.

``sio.engineio.*``
   Engine.IO transports, packets, sessions, heartbeat, and payload handling.

``sio.socketio.*``
   Socket.IO parser, packets, server, namespaces, sockets, rooms, and emits.

``sio.consumer``
   ``SocketIOConsumer`` registration, wiring, lifecycle hooks, and event
   dispatch.

Suggested development level
---------------------------

Use ``DEBUG`` while developing or diagnosing protocol issues.

Suggested production level
--------------------------

Use ``INFO`` in production for high-level lifecycle events, or a stricter level
if your operational logging budget requires it.
