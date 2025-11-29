# engineio/utils.py
from typing import Any
from urllib.parse import parse_qs


def parse_query(scope: dict[str, Any]) -> dict[str, str]:
    """
    Extract query params from ASGI scope as a flat dict[str, str].
    """
    raw = scope.get("query_string") or b""
    qs = parse_qs(raw.decode("ascii"), keep_blank_values=True)
    return {k: v[0] for k, v in qs.items() if v}
