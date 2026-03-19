from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ImageModelOption:
    key: str
    title: str
    api_model: str
    create_api_model: str
    cost: int
    details: str
    button_label: str


IMAGE_MODELS: Final[tuple[ImageModelOption, ...]] = (
    ImageModelOption(
        key="standard",
        title="Google Flash Image 2.5",
        api_model="gemini-2.5-flash-image",
        create_api_model="gemini-2.5-flash-image",
        cost=1,
        details="быстро и дёшево",
        button_label="Google Flash 2.5 (1 кр)",
    ),
    ImageModelOption(
        key="nano2",
        title="Google Flash Image 3.1",
        api_model="gemini-3.1-flash-image-preview",
        create_api_model="gemini-3.1-flash-image-preview",
        cost=3,
        details="лучше качество/детали",
        button_label="🆕 Google Flash 3.1 (3 кр)",
    ),
    ImageModelOption(
        key="pro",
        title="Google Pro Image 3",
        api_model="gemini-3-pro-image-preview",
        create_api_model="gemini-3-pro-image-preview",
        cost=4,
        details="максимум качества в текущем API",
        button_label="Google Pro 3 (4 кр)",
    ),
)

DEFAULT_IMAGE_MODEL_KEY: Final[str] = "standard"


def get_image_model(key: str) -> ImageModelOption:
    for option in IMAGE_MODELS:
        if option.key == key:
            return option
    return IMAGE_MODELS[0]


def is_image_model_key(key: str) -> bool:
    return any(option.key == key for option in IMAGE_MODELS)


def format_generations(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "кредит"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = "кредита"
    else:
        word = "кредитов"
    return f"{count} {word}"


def model_bullet_line(option: ImageModelOption) -> str:
    details = f" ({option.details})" if option.details else ""
    return f"• {option.title} — {format_generations(option.cost)}{details}"
