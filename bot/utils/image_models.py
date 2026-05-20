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

OTHER_IMAGE_MODELS: Final[tuple[ImageModelOption, ...]] = (
    ImageModelOption(
        key="gpt_image_2",
        title="GPT Image 2",
        api_model="openai:gpt-image@2",
        create_api_model="openai:gpt-image@2",
        cost=5,
        details="текст, логотипы, постеры, каталог",
        button_label="GPT Image 2 (5 ген)",
    ),
    ImageModelOption(
        key="flux2_max",
        title="FLUX.2 Max",
        api_model="bfl:7@1",
        create_api_model="bfl:7@1",
        cost=6,
        details="фотореализм, fashion, luxury",
        button_label="FLUX.2 Max (6 ген)",
    ),
    ImageModelOption(
        key="flux2_dev",
        title="FLUX.2 Dev",
        api_model="runware:400@1",
        create_api_model="runware:400@1",
        cost=2,
        details="тесты промптов, массовая генерация",
        button_label="FLUX.2 Dev (2 ген)",
    ),
    ImageModelOption(
        key="flux2_klein",
        title="FLUX.2 Klein 9B",
        api_model="runware:400@2",
        create_api_model="runware:400@2",
        cost=2,
        details="баланс цена/качество",
        button_label="FLUX.2 Klein 9B (2 ген)",
    ),
    ImageModelOption(
        key="wan27_image",
        title="Wan2.7 Image",
        api_model="alibaba:wan@2.7-image",
        create_api_model="alibaba:wan@2.7-image",
        cost=3,
        details="аниме, азиатский стиль",
        button_label="Wan2.7 Image (3 ген)",
    ),
)

ALL_IMAGE_MODELS: Final[tuple[ImageModelOption, ...]] = IMAGE_MODELS + OTHER_IMAGE_MODELS

DEFAULT_IMAGE_MODEL_KEY: Final[str] = "standard"


def get_image_model(key: str) -> ImageModelOption:
    for option in ALL_IMAGE_MODELS:
        if option.key == key:
            return option
    return IMAGE_MODELS[0]


def is_image_model_key(key: str) -> bool:
    return any(option.key == key for option in ALL_IMAGE_MODELS)


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
