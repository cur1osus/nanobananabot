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

# Kling 2.6 Pro accepts only these 1080p combinations (1:1 must be 1440x1440).
KLING_26_RATIO_DIMS: Final[Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "1:1": (1440, 1440),
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
    }
)

# Kling 2.5 Turbo Pro accepts only these 720p combinations (1:1 is 720x720).
KLING_25_RATIO_DIMS: Final[Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "1:1": (720, 720),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
    }
)

# Kling 3.0 4K supports only these exact dimension combinations.
KLING_3_4K_RATIO_DIMS: Final[Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "1:1": (2880, 2880),
        "16:9": (3840, 2160),
        "9:16": (2160, 3840),
    }
)

# "Kling 3.0" is backed by the Pro variant (1080p). The "4K" toggle switches to
# the 4K variant (hidden from the model grid) and back.
KLING_4K_MODEL_KEY: Final[str] = "3.0-4k"
KLING_4K_BASE_MODEL_KEY: Final[str] = "3.0"

# Durations offered for the Kling 3.0 family (spec allows 3-15s).
KLING3_DURATIONS: Final[tuple[int, ...]] = (5, 10, 15)
DEFAULT_DURATIONS: Final[tuple[int, ...]] = (5, 10)


@dataclass(frozen=True)
class KlingModelOption:
    key: str
    title: str
    runware_model: str
    cost_5s: int
    cost_10s: int
    cost_15s: int | None = None
    supports_duration: bool = False
    supports_dimensions: bool = False
    supports_sound: bool = False
    ratio_dims: Mapping[str, tuple[int, int]] = VIDEO_RATIO_DIMS
    # Durations (seconds) offered in the UI for this model.
    durations: tuple[int, ...] = DEFAULT_DURATIONS
    # Some Kling models need providerSettings.klingai when passing an image.
    needs_provider_settings: bool = False
    # Whether the model appears in the model-selection grid. The Pro/4K quality
    # tiers are hidden and activated only via their toggles.
    selectable: bool = True


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
    ),
    KlingModelOption(
        key="3.0",
        title="Kling 3.0",
        runware_model="klingai:kling-video@3-pro",
        cost_5s=20,
        cost_10s=35,
        cost_15s=50,
        supports_duration=True,
        supports_dimensions=True,
        supports_sound=True,
        ratio_dims=VIDEO_RATIO_DIMS,
        durations=KLING3_DURATIONS,
    ),
    KlingModelOption(
        key="3.0-4k",
        title="Kling 3.0 4K",
        runware_model="klingai:kling-video@3-4k",
        cost_5s=60,
        cost_10s=110,
        cost_15s=160,
        supports_duration=True,
        supports_dimensions=True,
        supports_sound=True,
        ratio_dims=KLING_3_4K_RATIO_DIMS,
        durations=KLING3_DURATIONS,
        selectable=False,
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
        # Pro (6@1) supports text-to-video; Standard (6@0) is image-to-video only.
        runware_model="klingai:6@1",
        cost_5s=10,
        cost_10s=18,
        supports_duration=True,
        supports_dimensions=True,
        supports_sound=False,
        ratio_dims=KLING_25_RATIO_DIMS,
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
    if duration >= 15 and model.cost_15s is not None:
        return model.cost_15s
    if duration >= 10:
        return model.cost_10s
    return model.cost_5s
