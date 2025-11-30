# engineio/__init__.py
import logging

from .constants import ENGINE_IO_VERSION
from .polling import LongPollingConsumer
from .websocket import EngineIOWebSocketConsumer

__version__ = f"v{ENGINE_IO_VERSION}"

logger = logging.getLogger("sio." + __name__)
logger.info(
    "engineio package imported",
    extra={"version": __version__, "engineio_version": ENGINE_IO_VERSION},
)

__all__ = ["EngineIOWebSocketConsumer", "LongPollingConsumer"]
