Tutorial Part 5: Testing
========================

The project includes integration tests using a real Channels live server and a
``python-socketio.AsyncClient``. This part shows the shape of such a test for
the tutorial chat app.

Install test dependencies
-------------------------

Use your normal test stack, plus ``pytest`` and the official Python Socket.IO
client:

.. code-block:: bash

   pip install pytest pytest-django python-socketio

Example integration test
------------------------

The exact live-server fixture depends on your project setup. The important part
is that the test connects a real Socket.IO client to your ASGI app.

.. code-block:: python

   import asyncio

   import pytest
   import socketio


   @pytest.mark.asyncio
   async def test_chat_message_over_websocket(live_server):
       client = socketio.AsyncClient()
       received = []

       @client.on("chat_message", namespace="/chat")
       async def on_chat_message(payload):
           received.append(payload)

       await client.connect(
           live_server.url,
           socketio_path="socket.io",
           namespaces=["/chat"],
           transports=["websocket"],
       )

       ack = await client.call(
           "chat_message",
           {"text": "Hello from test"},
           namespace="/chat",
           timeout=5,
       )

       await asyncio.sleep(0.1)
       await client.disconnect()

       assert ack == {"status": "ok"}
       assert {"text": "Hello from test"} in received

Testing both transports
-----------------------

Socket.IO clients can use WebSocket and HTTP long-polling. Test both when a
change touches transport, framing, session, or heartbeat behaviour.

.. code-block:: python

   @pytest.mark.parametrize("transport", ["websocket", "polling"])
   @pytest.mark.asyncio
   async def test_chat_message_transport(live_server, transport):
       client = socketio.AsyncClient()
       await client.connect(
           live_server.url,
           socketio_path="socket.io",
           namespaces=["/chat"],
           transports=[transport],
       )
       ack = await client.call(
           "chat_message",
           {"text": transport},
           namespace="/chat",
           timeout=5,
       )
       await client.disconnect()
       assert ack["status"] == "ok"

What the repository already tests
---------------------------------

The repository includes:

* unit tests for Engine.IO packet/session logic;
* unit tests for Socket.IO encoding, decoding, and parser behaviour;
* unit tests for namespace and room handling;
* unit tests for consumer wiring and disconnect hooks;
* integration tests using a real Channels live server and a
  ``python-socketio.AsyncClient``;
* integration coverage for the example app in ``tests/sample_project``;
* tests that exercise both polling and WebSocket transports.

Run the full test suite with:

.. code-block:: bash

   pytest

You can use coverage tools such as ``pytest-cov`` or ``coverage.py`` to inspect
branch coverage and verify that all protocol branches are exercised during
testing.
