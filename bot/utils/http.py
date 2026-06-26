from __future__ import annotations

import aiohttp

# Общий aiohttp-клиент на всё приложение: переиспользует пул соединений и
# TLS-сессии вместо создания новой ClientSession на каждый запрос (что давало
# лишние TCP/TLS-хендшейки на каждом скачивании и опросе API).
_session: aiohttp.ClientSession | None = None


def get_http_session() -> aiohttp.ClientSession:
    """Вернуть общий ClientSession, создавая его при первом обращении.

    Создаётся лениво внутри работающего event loop. Таймаут задаётся
    индивидуально на каждый запрос через параметр ``timeout``.
    """
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_http_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
