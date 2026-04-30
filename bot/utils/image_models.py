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
        title="Nano Banana",
        api_model="google:4@1",
        create_api_model="google:4@1",
        cost=1,
        details="быстро и дёшево",
        button_label="Nano Banana (1 ген)",
    ),
    ImageModelOption(
        key="nano2",
        title="Nano Banana 2",
        api_model="google:4@3",
        create_api_model="google:4@3",
        cost=3,
        details="лучше детализация",
        button_label="Nano Banana 2 (3 ген)",
    ),
    ImageModelOption(
        key="pro",
        title="Nano Banana Pro",
        api_model="google:4@2",
        create_api_model="google:4@2",
        cost=4,
        details="лучшее качество, но медленнее",
        button_label="Nano Banana Pro (4 ген)",
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
