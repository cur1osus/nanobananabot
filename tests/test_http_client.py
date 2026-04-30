from __future__ import annotations

from bot.utils.http_client import resolve_proxy_settings


def _clear_proxy_env(monkeypatch) -> None:
    for key in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.delenv(key, raising=False)


def test_resolve_proxy_settings_prefers_explicit_proxy(monkeypatch) -> None:
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:8080")

    settings = resolve_proxy_settings("socks5://explicit-proxy:1080")

    assert settings.explicit_proxy == "socks5://explicit-proxy:1080"
    assert settings.trust_env is False
    assert settings.source == "explicit"


def test_resolve_proxy_settings_uses_standard_proxy_env(monkeypatch) -> None:
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:8080")

    settings = resolve_proxy_settings("")

    assert settings.explicit_proxy is None
    assert settings.trust_env is True
    assert settings.source == "HTTPS_PROXY"


def test_resolve_proxy_settings_handles_missing_proxy(monkeypatch) -> None:
    _clear_proxy_env(monkeypatch)

    settings = resolve_proxy_settings("")

    assert settings.explicit_proxy is None
    assert settings.trust_env is False
    assert settings.source == "none"
