Deployment and scaling
======================

The default Engine.IO session registry is **in-memory and single-process**.
This is the most important production constraint in the current design.

What in-memory sessions mean
----------------------------

All Engine.IO sessions, for both polling and WebSocket transports, are stored in
the Python process that accepted the initial connection.

If you run multiple worker processes or multiple containers behind a load
balancer without sticky sessions, requests for the same client may hit a
different process. That process will not know the Engine.IO ``sid`` and the
connection will fail.

Production requirement
----------------------

In production you must either:

* run a single ASGI worker process; or
* configure your load balancer to use **sticky sessions**, also known as
  session affinity, so that all requests for a given client always reach the
  same process.

Channel layer role
------------------

The Channels channel layer, such as Redis, is used only for Socket.IO room
broadcasting. It does not provide shared storage for Engine.IO sessions.

This means Redis channel layers help with cross-process broadcast fan-out, but
they do not remove the sticky-session requirement for Engine.IO session lookup.

ASGI servers
------------

``django-sio`` runs inside Django Channels, so it can be served by an ASGI
server that supports the Channels stack, such as Daphne or Uvicorn configured
for your project.

Whichever server you choose, make sure:

* HTTP and WebSocket traffic for ``/socket.io`` reaches the ASGI application;
* proxy timeouts are longer than the Engine.IO ping interval and timeout;
* WebSocket upgrade headers are forwarded correctly by your reverse proxy;
* sticky sessions are enabled when more than one process/container can receive
  traffic.

Future session storage
----------------------

A future version may expose a pluggable session registry interface for more
advanced deployments. The current design assumes in-process sessions.
