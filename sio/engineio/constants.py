# engineio/constants.py

ENGINE_IO_VERSION = "4"

# --------------------------------------------------------------------------- #
# Django-backed configuration
# --------------------------------------------------------------------------- #

from django.conf import settings as django_settings  # type: ignore


def _get_setting(name: str, default: int) -> int:
    """
    Allow Engine.IO defaults to be overridden from Django settings.

    We look for SIO_ENGINEIO_* keys on django.conf.settings, but only if
    Django is installed AND configured. Otherwise we silently fall back to
    the hard-coded defaults.
    """
    if django_settings is None:
        return default

    # settings.configured may not exist on very old Djangos, so be defensive
    configured = getattr(django_settings, "configured", True)
    if not configured:
        return default

    return getattr(django_settings, name, default)


# Default config (can be overridden in Django settings)
# e.g. in settings.py:
#   SIO_ENGINEIO_PING_INTERVAL_MS = 15_000
#   SIO_ENGINEIO_PING_TIMEOUT_MS = 10_000
#   SIO_ENGINEIO_MAX_PAYLOAD_BYTES = 2_000_000

PING_INTERVAL_MS = _get_setting("SIO_ENGINEIO_PING_INTERVAL_MS", 25_000)
PING_TIMEOUT_MS = _get_setting("SIO_ENGINEIO_PING_TIMEOUT_MS", 20_000)
MAX_PAYLOAD_BYTES = _get_setting("SIO_ENGINEIO_MAX_PAYLOAD_BYTES", 1_000_000)

# Transports
TRANSPORT_POLLING = "polling"
TRANSPORT_WEBSOCKET = "websocket"

# HTTP long-polling specifics
RECORD_SEPARATOR = "\x1e"  # used to separate packets in HTTP payloads

# Default request path (you can override in routing)
ENGINEIO_PATH = "/engine.io/"
