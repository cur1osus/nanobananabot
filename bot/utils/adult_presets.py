from __future__ import annotations

from typing import Final

# Возрастная пометка добавляется к КАЖДОМУ пресету автоматически. Это юридическая
# и провайдерская страховка: контент только про совершеннолетних. Не убирать.
ADULT_AGE_TAG: Final[str] = "adult woman, 25 years old, "

# Готовые пресеты быстрых промптов для раздела 18+.
# Формат: (надпись на кнопке, текст промпта). Текст наполняется владельцем бота —
# описывай сцены ТОЛЬКО про совершеннолетних. Возрастная пометка добавится сама.
# Пример строки:
#   ("Пляж", "девушка в купальнике на пляже"),
ADULT_PRESETS: Final[tuple[tuple[str, str], ...]] = (
)


def build_preset_prompt(preset_prompt: str) -> str:
    """Собрать финальный промпт пресета с обязательной возрастной пометкой."""
    return f"{ADULT_AGE_TAG}{preset_prompt}".strip()


def get_adult_preset(index: int) -> str | None:
    if 0 <= index < len(ADULT_PRESETS):
        return ADULT_PRESETS[index][1]
    return None
