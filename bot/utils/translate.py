from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)

_GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


def _has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


async def translate_prompt_to_english(text: str) -> str:
    """Перевести промпт на английский через Google Translate (без ключа, без LLM).

    Машинный перевод не «зажимается» на explicit-тексте, в отличие от LLM. При любой
    ошибке/таймауте возвращает исходный текст, чтобы не блокировать генерацию. Текст
    без кириллицы считается уже английским и не переводится.
    """
    stripped = text.strip()
    if not stripped or not _has_cyrillic(stripped):
        return stripped

    params = {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": stripped}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _GOOGLE_TRANSLATE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Google translate HTTP %s, using original", resp.status)
                    return stripped
                data = await resp.json(content_type=None)
        # data[0] — список сегментов вида [translated, original, ...]
        translated = "".join(
            seg[0] for seg in data[0] if seg and seg[0]
        ).strip()
        return translated if len(translated) >= 2 else stripped
    except Exception:
        logger.warning("Google translate failed, using original prompt", exc_info=True)
        return stripped
