# engineio/constants.py
import logging

from django.conf import settings as django_settings  # type: ignore

logger = logging.getLogger("sio." + __name__)

ENGINE_IO_VERSION = "4"


def _get_setting(name: str, default: int) -> int:
    """
    Allow Engine.IO defaults to be overridden from Django settings.

    We look for SIO_ENGINEIO_* keys on django.conf.settings, but only if
    Django is installed AND configured. Otherwise we silently fall back to
    the hard-coded defaults.
    """
    if django_settings is None:
        logger.debug(
            "Django settings unavailable, using default for %s=%s",
            name,
            default,
        )
        return default

    configured = getattr(django_settings, "configured", True)
    if not configured:
        logger.debug(
            "Django settings not configured, using default for %s=%s",
            name,
            default,
        )
        return default

    value = getattr(django_settings, name, default)
    logger.debug(
        "Engine.IO setting %s=%s (default=%s)", name, value, default
    )
    return value


# Default config (can be overridden in Django settings)
PING_INTERVAL_MS = _get_setting("SIO_ENGINEIO_PING_INTERVAL_MS", 25_000)
PING_TIMEOUT_MS = _get_setting("SIO_ENGINEIO_PING_TIMEOUT_MS", 20_000)
MAX_PAYLOAD_BYTES = _get_setting("SIO_ENGINEIO_MAX_PAYLOAD_BYTES", 1_000_000)

logger.info(
    "Engine.IO constants initialised",
    extra={
        "engineio_version": ENGINE_IO_VERSION,
        "ping_interval_ms": PING_INTERVAL_MS,
        "ping_timeout_ms": PING_TIMEOUT_MS,
        "max_payload_bytes": MAX_PAYLOAD_BYTES,
    },
)

# Transports
TRANSPORT_POLLING = "polling"
TRANSPORT_WEBSOCKET = "websocket"

# HTTP long-polling specifics
RECORD_SEPARATOR = "\x1e"  # used to separate packets in HTTP payloads

# Default request path (you can override in routing)
ENGINEIO_PATH = "/engine.io/"
