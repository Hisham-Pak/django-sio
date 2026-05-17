Production checklist
====================

Use this checklist before deploying ``django-sio``.

Routing
-------

* Route ``/socket.io`` for both HTTP and WebSocket scopes.
* Put the Socket.IO HTTP route before the normal Django fallback route.
* Ensure your reverse proxy forwards WebSocket upgrade headers.

Workers and sessions
--------------------

* Remember that Engine.IO sessions are stored in-process.
* Use a single ASGI worker process, or enable sticky sessions/session affinity.
* Do not rely on the Channels channel layer for Engine.IO session storage.

Channel layer
-------------

* Use a production channel layer such as Redis for room broadcasting.
* Keep in mind that Redis broadcasting does not replace sticky sessions.

Timeouts
--------

* Review ``SIO_ENGINEIO_PING_INTERVAL_MS``.
* Review ``SIO_ENGINEIO_PING_TIMEOUT_MS``.
* Configure proxy/server idle timeouts so they do not close healthy Socket.IO
  connections too early.

Payloads
--------

* Review ``SIO_ENGINEIO_MAX_PAYLOAD_BYTES`` if you send large messages over
  HTTP long-polling.
* Prefer small event payloads when possible.

Logging
-------

* Use ``DEBUG`` logging in staging when validating transport behaviour.
* Use ``INFO`` logging in production for high-level lifecycle events.
* Send ``sio`` logs to your normal Django logging handler or aggregator.

Tests
-----

* Test WebSocket transport.
* Test polling transport.
* Test connection, disconnection, acks, room joins, room leaves, and room
  broadcasts.
