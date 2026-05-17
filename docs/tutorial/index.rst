Tutorial
========

This tutorial builds a small Socket.IO chat server inside a Django project.
It uses one Socket.IO namespace, one room, browser JavaScript as the first
client, and optional Python tests at the end.

What you will build
-------------------

By the end you will have:

* a Django project configured for Channels and ``django-sio``;
* a ``ChatConsumer`` mounted at the Socket.IO path ``/socket.io``;
* a ``/chat`` namespace;
* a ``lobby`` room;
* a ``chat_message`` event with acknowledgement support;
* browser client code using the official Socket.IO JavaScript client;
* a basic integration-test pattern using ``python-socketio.AsyncClient``.

Tutorial parts
--------------

.. toctree::
   :maxdepth: 1

   part-1-basic-setup
   part-2-chat-consumer
   part-3-routing-and-client
   part-4-rooms-and-acks
   part-5-testing
