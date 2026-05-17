Testing and development
=======================

The repository includes both unit tests and integration tests.

Unit tests
----------

Unit tests cover:

* Engine.IO packet and session logic;
* Socket.IO encoding, decoding, and parser behaviour;
* namespace and room handling;
* consumer wiring;
* disconnect hooks.

Integration tests
-----------------

Integration tests use a real Channels live server and a
``python-socketio.AsyncClient``. They talk to the example app in
``tests/sample_project`` and exercise both polling and WebSocket transports.

Run tests
---------

Run the full test suite with:

.. code-block:: bash

   pytest

Coverage
--------

Use coverage tools such as ``pytest-cov`` or ``coverage.py`` to inspect branch
coverage and verify that protocol branches are exercised during testing.

A useful local command is:

.. code-block:: bash

   pytest --cov=sio --cov-report=term-missing

Development logging
-------------------

When debugging tests, enable the ``sio`` logger at ``DEBUG`` level. See
:doc:`logging` for a complete Django ``LOGGING`` example.

Transport matrix
----------------

When changing Engine.IO code, test both transports:

* ``polling`` for HTTP long-polling payload framing and batching;
* ``websocket`` for WebSocket frames, upgrade behaviour, and heartbeat loops.

When changing Socket.IO parser or namespace code, test:

* namespace connection and disconnection;
* event dispatch;
* acknowledgements;
* room joins and leaves;
* room broadcasts.
