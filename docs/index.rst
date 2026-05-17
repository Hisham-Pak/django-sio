django-sio
==========

Socket.IO for Django, powered by Channels and compatible with the official
Socket.IO clients.

``django-sio`` implements the Socket.IO v5 protocol on top of an in-process
Engine.IO v4 server, using Django Channels for HTTP/WebSocket handling and
broadcasts.

It is designed to work with the official Socket.IO clients: browser JavaScript,
Node.js, ``python-socketio``, and other Socket.IO-compatible clients.

What this gives you
-------------------

* A **Socket.IO server** running inside Django/Channels.
* Support for both **WebSocket and HTTP long-polling**.
* A simple, class-based **consumer API**:

  * ``connect(self, socket, auth)``
  * ``disconnect(self, socket, reason)``
  * ``event_<name>(self, socket, *args, ack=None)``

If you already know Socket.IO from Node.js, this behaves very similarly on the
server side, but lives inside your Django project.

Getting started
---------------

New to the project? Start with :doc:`introduction`, then follow the
:doc:`tutorial/index`.

Already using Django Channels? Jump to :doc:`installation` and
:doc:`topics/routing`.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: First steps

   introduction
   installation
   tutorial/index

.. toctree::
   :maxdepth: 2
   :caption: Topics

   topics/consumers
   topics/routing
   topics/clients
   topics/configuration
   topics/logging
   topics/architecture
   topics/deployment
   topics/testing

.. toctree::
   :maxdepth: 2
   :caption: How-to guides

   howto/add-to-existing-project
   howto/broadcast-from-handlers
   howto/production-checklist

.. toctree::
   :maxdepth: 2
   :caption: Reference

   reference/consumer-api
   reference/socket-api
   reference/settings
   reference/protocol-layers
   reference/loggers
