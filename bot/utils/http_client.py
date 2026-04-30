from __future__ import annotations

import os
from dataclasses import dataclass

import aiohttp

_PROXY_ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


@dataclass(frozen=True)
class ProxySettings:
    explicit_proxy: str | None
    trust_env: bool
    source: str


def resolve_proxy_settings(explicit_proxy: str = "") -> ProxySettings:
    proxy = explicit_proxy.strip()
    if proxy:
        return ProxySettings(
            explicit_proxy=proxy,
            trust_env=False,
            source="explicit",
        )

    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return ProxySettings(
                explicit_proxy=None,
                trust_env=True,
                source=key,
            )

    return ProxySettings(
        explicit_proxy=None,
        trust_env=False,
        source="none",
    )


def create_client_session(
    *,
    timeout: aiohttp.ClientTimeout | None = None,
    proxy_settings: ProxySettings | None = None,
) -> aiohttp.ClientSession:
    session_kwargs: dict[str, object] = {}
    if timeout is not None:
        session_kwargs["timeout"] = timeout
    if proxy_settings is not None:
        session_kwargs["trust_env"] = proxy_settings.trust_env
    return aiohttp.ClientSession(**session_kwargs)
