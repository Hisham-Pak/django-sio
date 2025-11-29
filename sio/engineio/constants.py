# engineio/constants.py

ENGINE_IO_VERSION = "4"

# Default config as in Engine.IO docs
PING_INTERVAL_MS = 300
PING_TIMEOUT_MS = 200
MAX_PAYLOAD_BYTES = 1_000_000

# Transports
TRANSPORT_POLLING = "polling"
TRANSPORT_WEBSOCKET = "websocket"

# HTTP long-polling specifics
RECORD_SEPARATOR = "\x1e"  # used to separate packets in HTTP payloads

# Default request path (you can override in routing)
ENGINEIO_PATH = "/engine.io/"
