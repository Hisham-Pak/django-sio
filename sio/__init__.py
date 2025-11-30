# __init__.py (root package)
import logging

from .socketio.constants import DEFAULT_NAMESPACE, SOCKET_IO_VERSION
from .socketio.socket import NamespaceSocket
from .socketio.protocol import SocketIOPacket, SocketIOParser
from .socketio.server import SocketIOServer, get_socketio_server
from .consumer import SocketIOConsumer, get_socketio_server

__version__ = "v0.1.0"

logger = logging.getLogger("sio." + __name__)
logger.info(
    "sio root package imported",
    extra={
        "version": __version__,
        "socketio_version": SOCKET_IO_VERSION,
        "default_namespace": DEFAULT_NAMESPACE,
    },
)

__all__ = [
    "DEFAULT_NAMESPACE",
    "SOCKET_IO_VERSION",
    "NamespaceSocket",
    "SocketIOConsumer",
    "SocketIOPacket",
    "SocketIOParser",
    "SocketIOServer",
    "get_socketio_server",
]
