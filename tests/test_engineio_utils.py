from __future__ import annotations

from sio.engineio.utils import parse_query


def test_parse_query_normal_and_empty():
    scope = {"query_string": b"a=1&b=2&empty="}
    qs = parse_query(scope)
    assert qs == {"a": "1", "b": "2", "empty": ""}

    # no query_string key
    qs2 = parse_query({})
    assert qs2 == {}
