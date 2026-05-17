Configuration
=============

Engine.IO timing and payload limits
-----------------------------------

By default, the Engine.IO layer uses conservative defaults for heartbeats and
HTTP payload limits. These can be overridden globally via Django settings.

Supported settings
~~~~~~~~~~~~~~~~~~

``SIO_ENGINEIO_PING_INTERVAL_MS``
   Interval, in milliseconds, between server-to-client pings.

   Default: ``25_000`` (25 seconds)

``SIO_ENGINEIO_PING_TIMEOUT_MS``
   Time, in milliseconds, the server waits for a pong after sending a ping
   before considering the connection dead.

   Default: ``20_000`` (20 seconds)

``SIO_ENGINEIO_MAX_PAYLOAD_BYTES``
   Maximum size, in bytes, of a single HTTP long-polling payload. Engine.IO
   packets queued for polling are batched up to this limit; any segments that do
   not fit are delivered in a subsequent response.

   Default: ``1_000_000`` (1 MB)

Example settings
~~~~~~~~~~~~~~~~

.. code-block:: python

   # Engine.IO timing / payload tuning (optional)
   SIO_ENGINEIO_PING_INTERVAL_MS = 25_000      # default 25_000
   SIO_ENGINEIO_PING_TIMEOUT_MS = 20_000       # default 20_000
   SIO_ENGINEIO_MAX_PAYLOAD_BYTES = 1_000_000  # default 1_000_000

How settings are used
~~~~~~~~~~~~~~~~~~~~~

These values are read once at import time by the Engine.IO implementation and
are used consistently across:

* the Engine.IO ``open`` packet sent to clients, including the ``pingInterval``,
  ``pingTimeout``, and ``maxPayload`` fields;
* the HTTP long-polling timeout and batching;
* the WebSocket heartbeat loop.

They are **global** settings for the entire process. Per-session overrides are
not currently supported.

When to change them
~~~~~~~~~~~~~~~~~~~

For most applications you do not need to touch these settings.

You may want to lower the ping interval or timeout for latency-sensitive apps,
or increase ``SIO_ENGINEIO_MAX_PAYLOAD_BYTES`` if you know you will be sending
larger messages over HTTP long-polling and are comfortable with the trade-off in
request size versus frequency.
