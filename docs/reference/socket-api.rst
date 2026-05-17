Socket API reference
====================

``NamespaceSocket`` represents one client connected to one Socket.IO namespace.
Consumer hooks and event handlers receive it as the ``socket`` argument.

Common attributes
-----------------

``socket.namespace``
   The Socket.IO namespace for this socket, such as ``"/chat"``.

``socket.server``
   The ``SocketIOServer`` instance. Use it for namespace or room-wide emits.

Common methods
--------------

``await socket.emit(event, data=None, **options)``
   Emit an event to the current client in the current namespace.

``await socket.send(data=None, **options)``
   Send a Socket.IO message event to the current client.

``await socket.join(room)``
   Add the socket to a room in its namespace.

``await socket.leave(room)``
   Remove the socket from a room in its namespace.

``await socket.leave_all()``
   Remove the socket from all rooms it has joined.

``await socket.disconnect()``
   Disconnect this namespace socket.

Server emits
------------

Use ``socket.server.emit`` when broadcasting:

.. code-block:: python

   await socket.server.emit(
       "chat_message",
       {"text": "Hello"},
       room="lobby",
       namespace=socket.namespace,
   )

The ``room`` argument targets a room. The ``namespace`` argument keeps the
broadcast scoped to the correct Socket.IO namespace.
