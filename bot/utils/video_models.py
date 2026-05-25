from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


DEFAULT_KLING_MODEL_KEY: Final[str] = "2.6"
DEFAULT_VIDEO_DURATION: Final[int] = 5
DEFAULT_VIDEO_RATIO: Final[str] = "1:1"

VIDEO_RATIO_MAP: Final[Mapping[str, str]] = MappingProxyType(
    {
        "1x1": "1:1",
        "16x9": "16:9",
        "9x16": "9:16",
    }
)

VIDEO_RATIOS: Final[tuple[str, ...]] = ("1:1", "16:9", "9:16")

VIDEO_RATIO_DIMS: Final[Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "1:1": (1440, 1440),
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
    }
)

KLING_26_RATIO_DIMS: Final[Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "1:1": (1080, 1080),
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
    }
)


@dataclass(frozen=True)
class KlingModelOption:
    key: str
    title: str
    runware_model: str
    cost_5s: int
    cost_10s: int
    supports_duration: bool = False
    supports_dimensions: bool = False
    supports_sound: bool = False
    ratio_dims: Mapping[str, tuple[int, int]] = VIDEO_RATIO_DIMS
    # Some Kling models need providerSettings.klingai when passing an image.
    needs_provider_settings: bool = False


KLING_MODELS: Final[tuple[KlingModelOption, ...]] = (
    KlingModelOption(
        key="2.6",
        title="Kling 2.6",
        runware_model="klingai:kling-video@2.6-pro",
        cost_5s=25,
        cost_10s=45,
        supports_duration=True,
        supports_dimensions=True,
        supports_sound=True,
        ratio_dims=KLING_26_RATIO_DIMS,
        needs_provider_settings=True,
    ),
    KlingModelOption(
        key="3.0",
        title="Kling 3.0",
        runware_model="klingai:kling-video@o3-standard",
        cost_5s=20,
        cost_10s=35,
        supports_duration=True,
        supports_dimensions=True,
        supports_sound=True,
    ),
    KlingModelOption(
        key="o1",
        title="Kling O1",
        runware_model="klingai:kling@o1",
        cost_5s=15,
        cost_10s=25,
        supports_duration=True,
        supports_dimensions=True,
        supports_sound=False,
    ),
    KlingModelOption(
        key="2.5turbo",
        title="Kling 2.5 Turbo",
        runware_model="klingai:6@0",
        cost_5s=10,
        cost_10s=18,
        supports_duration=False,
        supports_dimensions=False,
        supports_sound=False,
    ),
)


def get_kling_model(key: str) -> KlingModelOption:
    for option in KLING_MODELS:
        if option.key == key:
            return option
    return KLING_MODELS[0]


def is_kling_model_key(key: str) -> bool:
    return any(option.key == key for option in KLING_MODELS)


def video_cost(model_key: str, duration: int) -> int:
    model = get_kling_model(model_key)
    if not model.supports_duration:
        return model.cost_5s
    return model.cost_5s if duration == 5 else model.cost_10s
