from __future__ import annotations

from typing import Final

# Ключ-плейсхолдер для распознанной одежды. Если он есть в тексте пресета, бот
# делает OCR одежды на загруженном фото и разворачивает ключ в список вещей через
# запятую. Если одежды в кадре нет — такой пресет применять нельзя (отказ).
CLOTHING_KEY: Final[str] = "{clothing}"

# Готовые пресеты быстрых промптов для раздела 18+.
# Формат: (надпись на кнопке, текст промпта). Текст наполняется владельцем бота —
# описывай сцены ТОЛЬКО про совершеннолетних. Возрастная пометка добавится сама.
# Можно вставить ключ {clothing} — он развернётся в список одежды с фото.
# Примеры строк:
#   ("Пляж", "девушка в купальнике на пляже"),
#   ("Снять одежду", "removes {clothing}, fully nude"),
ADULT_PRESETS: Final[tuple[tuple[str, str], ...]] = (
)


def preset_requires_clothing(preset_prompt: str) -> bool:
    """Содержит ли пресет ключ одежды (нужен ли OCR фото)."""
    return CLOTHING_KEY in preset_prompt


def expand_clothing_key(preset_prompt: str, items: list[str]) -> str:
    """Развернуть ключ {clothing} в список вещей через запятую."""
    return preset_prompt.replace(CLOTHING_KEY, ", ".join(items))


def build_preset_prompt(preset_prompt: str) -> str:
    """Собрать финальный промпт пресета."""
    return preset_prompt.strip()


def get_adult_preset(index: int) -> str | None:
    if 0 <= index < len(ADULT_PRESETS):
        return ADULT_PRESETS[index][1]
    return None
