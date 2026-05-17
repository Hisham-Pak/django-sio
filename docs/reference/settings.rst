Settings reference
==================

``SIO_ENGINEIO_PING_INTERVAL_MS``
---------------------------------

Default: ``25_000``

Interval, in milliseconds, between server-to-client pings.

``SIO_ENGINEIO_PING_TIMEOUT_MS``
--------------------------------

Default: ``20_000``

Time, in milliseconds, the server waits for a pong after sending a ping before
considering the connection dead.

``SIO_ENGINEIO_MAX_PAYLOAD_BYTES``
----------------------------------

Default: ``1_000_000``

Maximum size, in bytes, of a single HTTP long-polling payload.

Engine.IO packets queued for polling are batched up to this limit. Segments that
do not fit are delivered in a subsequent response.

Import-time behaviour
---------------------

These settings are read once at import time by the Engine.IO implementation.
They are global for the process. Per-session overrides are not currently
supported.

Used by
-------

These values are used by:

* the Engine.IO ``open`` packet sent to clients;
* ``pingInterval``;
* ``pingTimeout``;
* ``maxPayload``;
* HTTP long-polling timeout and batching;
* WebSocket heartbeat loop.
