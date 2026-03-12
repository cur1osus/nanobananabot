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
        title="Standard",
        api_model="img2img-google/flash-25-edit-multi",
        create_api_model="img-google/flash-25",
        cost=1,
        details="",
        button_label="Standard (1 кр)",
    ),
    ImageModelOption(
        key="nano2",
        title="Nano Banana 2",
        api_model="img2img-google/nano-banana-2-edit-multi",
        create_api_model="img-google/nano-banana-2",
        cost=3,
        details="4K, тренды",
        button_label="🆕 Nano Banana 2 (3 кр)",
    ),
    ImageModelOption(
        key="pro",
        title="Pro",
        api_model="img2img-google/nano-banana-pro-edit-multi",
        create_api_model="img-google/nano-banana-pro",
        cost=4,
        details="4K, максимум качества",
        button_label="Pro (4 кр)",
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
