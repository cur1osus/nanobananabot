from __future__ import annotations

import base64
import json
import logging
import re

import aiohttp

from bot.settings import se

logger = logging.getLogger(__name__)


class ClothingOCRError(Exception):
    """Ошибка распознавания одежды через Agent Platform."""


# Просим модель вернуть строго JSON-массив коротких РУССКИХ названий одежды —
# пресеты в боте на русском, перевода нет, поэтому список должен лечь в промпт
# на том же языке. Явно перечисляем бельё/купальники: это рабочий сценарий
# раздела, иначе модель их пропускает или «уходит в отказ». Аксессуары
# (украшения, очки, сумки) исключаем — они только зашумляют список для снятия.
_OCR_PROMPT = (
    "Ты точный детектор одежды для фоторедактора. "
    "Перечисли каждую вещь одежды, НАДЕТУЮ на человеке(-ах) на фото, включая "
    "нижнее бельё, бюстгальтер, трусы, лифчик, купальник, бикини, чулки, носки "
    "и обувь. НЕ включай украшения, очки, часы, сумки и другие аксессуары, "
    "а также вещи, которые не надеты (лежат рядом). "
    'Используй короткие русские названия (например: "белая футболка", "клетчатая рубашка", "юбка"). '
    'Ответь ТОЛЬКО JSON-массивом строк и ничем больше, например: ["платье", "бюстгальтер"]. '
    "Если надетой одежды на фото нет совсем, ответь []."
)


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _parse_items(content: str) -> list[str]:
    """Достать список вещей из ответа модели (с защитой от markdown-обёртки)."""
    text = content.strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    raw = match.group(0) if match else text
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []

    items: list[str] = []
    seen: set[str] = set()
    for entry in data:
        item = str(entry).strip().strip(".,;").lower()
        if item and item not in seen:
            seen.add(item)
            items.append(item)
    return items


def _extract_content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        # Некоторые провайдеры возвращают content как список частей.
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content or "")


async def detect_clothing_items(image_bytes: bytes) -> list[str]:
    """Распознать одежду на фото. Возвращает список вещей (рус.) или [] если её нет.

    Поднимает ClothingOCRError при сетевой/API-ошибке — это надо отличать от
    «одежды на фото нет» (пустой список), чтобы не отказывать пользователю зря.
    """
    if not se.agent_platform.api_key:
        raise ClothingOCRError("AGENT_PLATFORM_API_KEY не задан.")

    data_url = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('ascii')}"
    payload = {
        "model": se.agent_platform.vision_model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {se.agent_platform.api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=se.agent_platform.timeout)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                _chat_url(se.agent_platform.base_url),
                headers=headers,
                json=payload,
            ) as response:
                data = await response.json()
                if response.status >= 400:
                    message = (
                        (data.get("error") or {}).get("message")
                        or data.get("message")
                        or str(data)
                    )
                    raise ClothingOCRError(
                        f"Agent Platform OCR error {response.status}: {message}"
                    )
    except aiohttp.ClientError as err:
        raise ClothingOCRError(f"Ошибка соединения с Agent Platform: {err}") from err

    choices = data.get("choices") or []
    if not choices:
        raise ClothingOCRError("Agent Platform не вернул ответ для OCR одежды.")

    content = _extract_content(choices[0].get("message") or {})
    items = _parse_items(content)
    logger.info(
        "Clothing OCR (%s): raw=%r -> items=%s",
        se.agent_platform.vision_model,
        content[:300],
        items,
    )
    return items
