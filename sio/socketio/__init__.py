# socketio/__init__.py
from __future__ import annotations

import logging

from .constants import DEFAULT_NAMESPACE, SOCKET_IO_VERSION
from .protocol import SocketIOPacket, SocketIOParser
from .server import Namespace, SocketIOServer, get_socketio_server
from .socket import NamespaceSocket

__version__ = f"v{SOCKET_IO_VERSION}"

logger = logging.getLogger("sio." + __name__)
logger.info(
    "socketio package imported",
    extra={"version": __version__},
)

__all__ = [
    "DEFAULT_NAMESPACE",
    "SOCKET_IO_VERSION",
    "Namespace",
    "NamespaceSocket",
    "SocketIOPacket",
    "SocketIOParser",
    "SocketIOServer",
    "get_socketio_server",
]
