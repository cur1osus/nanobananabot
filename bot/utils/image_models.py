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
    provider: str = "runware"
    # Дополнительные параметры генерации (используются для 18+ SDXL/Pony моделей).
    prompt_prefix: str = ""  # дописывается в начало позитивного промпта (score-теги Pony)
    negative_prompt: str = ""  # передаётся как negativePrompt
    img2img_mode: str = "reference"  # "seed" — классический SDXL img2img через seedImage
    steps: int | None = None  # число шагов; None — дефолт провайдера
    cfg_scale: float | None = None  # CFGScale; None — дефолт провайдера


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
        cost=1,
        details="быстрые черновики",
        button_label="FLUX.2 Klein 9B (1 ген)",
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

# +18 (NSFW) модели через Runware (open-weights SDXL/Pony чекпойнты с CivitAI).
# Доступ к разделу закрыт age-gate. У этих моделей нет встроенной модерации, в отличие
# от проприетарных FLUX.2 Max/Pro (те всегда возвращали "Request Moderated").
# AIR-идентификаторы проверены через Runware Model Search и доступны нашему ключу.

# Раздел 18+: единственная модель FLUX.2 Klein 9B через Prodia (open-weights, без
# модерации). Максимально базовая конфигурация — без префиксов/negative и без
# переопределения steps/guidance (используются дефолты Prodia).
ADULT_IMAGE_MODELS: Final[tuple[ImageModelOption, ...]] = (
    ImageModelOption(
        key="adult_flux_klein",
        title="Генерация 18+",
        api_model="inference.flux-2.klein.9b.img2img.v1",
        create_api_model="inference.flux-2.klein.9b.txt2img.v1",
        cost=1,
        details="без цензуры",
        button_label="Генерация 18+",
        provider="prodia",
    ),
)

ALL_IMAGE_MODELS: Final[tuple[ImageModelOption, ...]] = (
    IMAGE_MODELS + OTHER_IMAGE_MODELS + ADULT_IMAGE_MODELS
)

DEFAULT_IMAGE_MODEL_KEY: Final[str] = "standard"
DEFAULT_ADULT_IMAGE_MODEL_KEY: Final[str] = "adult_flux_klein"


def get_image_model(key: str) -> ImageModelOption:
    for option in ALL_IMAGE_MODELS:
        if option.key == key:
            return option
    return IMAGE_MODELS[0]


def is_image_model_key(key: str) -> bool:
    return any(option.key == key for option in ALL_IMAGE_MODELS)


def is_adult_model_key(key: str) -> bool:
    return any(option.key == key for option in ADULT_IMAGE_MODELS)


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
