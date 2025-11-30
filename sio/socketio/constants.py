# socketio/constants.py
import logging

logger = logging.getLogger("sio." + __name__)

# Socket.IO protocol v5 (used by Socket.IO v3+ and v4+).
SOCKET_IO_VERSION = 5

# Packet types
SIO_CONNECT = 0
SIO_DISCONNECT = 1
SIO_EVENT = 2
SIO_ACK = 3
SIO_CONNECT_ERROR = 4
SIO_BINARY_EVENT = 5
SIO_BINARY_ACK = 6

# Default namespace
DEFAULT_NAMESPACE = "/"

logger.info(
    "Socket.IO constants initialised",
    extra={
        "socketio_version": SOCKET_IO_VERSION,
        "default_namespace": DEFAULT_NAMESPACE,
    },
)
