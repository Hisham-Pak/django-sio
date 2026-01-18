# __init__.py (root package)
import logging

from .consumer import SocketIOConsumer

__version__ = "v0.1.0"

logger = logging.getLogger("sio." + __name__)
logger.info(
    "sio root package imported",
    extra={
        "version": __version__,
    },
)

__all__ = [
    "SocketIOConsumer",
]
