from __future__ import annotations

from importlib import reload
from types import SimpleNamespace

from django.test import override_settings

import sio.engineio.constants as const_mod


def test_engineio_constants_have_int_values():
    """
    Basic sanity check that the timing / payload constants are integers.
    """
    import sio.engineio.constants as const_mod

    reload(const_mod)

    assert isinstance(const_mod.PING_INTERVAL_MS, int)
    assert isinstance(const_mod.PING_TIMEOUT_MS, int)
    assert isinstance(const_mod.MAX_PAYLOAD_BYTES, int)


@override_settings(
    SIO_ENGINEIO_PING_INTERVAL_MS=1234,
    SIO_ENGINEIO_PING_TIMEOUT_MS=5678,
    SIO_ENGINEIO_MAX_PAYLOAD_BYTES=999_999,
)
def test_engineio_constants_reflect_django_settings():
    """
    With override_settings, reloading engineio.constants should pick up the
    overridden Django settings.
    """
    import sio.engineio.constants as const_mod

    # Reload so PING_* / MAX_PAYLOAD_BYTES are recomputed with the overridden
    # settings
    reload(const_mod)

    assert const_mod.PING_INTERVAL_MS == 1234
    assert const_mod.PING_TIMEOUT_MS == 5678
    assert const_mod.MAX_PAYLOAD_BYTES == 999_999

def test_get_setting_returns_default_when_django_settings_is_none(caplog, monkeypatch):
    monkeypatch.setattr(const_mod, "django_settings", None)

    value = const_mod._get_setting("SIO_ENGINEIO_PING_INTERVAL_MS", 25_000)

    assert value == 25_000


def test_get_setting_returns_default_when_django_settings_not_configured(caplog, monkeypatch):
    fake_settings = SimpleNamespace(configured=False)
    monkeypatch.setattr(const_mod, "django_settings", fake_settings)

    value = const_mod._get_setting("SIO_ENGINEIO_PING_TIMEOUT_MS", 20_000)

    assert value == 20_000
