from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class KlingModelOption:
    key: str
    title: str
    runware_model: str
    cost_5s: int
    cost_10s: int


KLING_MODELS: Final[tuple[KlingModelOption, ...]] = (
    KlingModelOption(
        key="2.6",
        title="Kling 2.6",
        runware_model="klingai:kling-video@2.6-standard",
        cost_5s=10,
        cost_10s=20,
    ),
    KlingModelOption(
        key="3.0",
        title="Kling 3.0 🆕",
        runware_model="klingai:kling-video@3-standard",
        cost_5s=15,
        cost_10s=30,
    ),
    KlingModelOption(
        key="o1",
        title="Kling O1",
        runware_model="klingai:kling@o1-standard",
        cost_5s=12,
        cost_10s=24,
    ),
    KlingModelOption(
        key="2.5turbo",
        title="Kling 2.5 Turbo",
        runware_model="klingai:6@0",
        cost_5s=8,
        cost_10s=16,
    ),
)

DEFAULT_KLING_MODEL_KEY: Final[str] = "2.6"
DEFAULT_VIDEO_DURATION: Final[int] = 5
DEFAULT_VIDEO_RATIO: Final[str] = "1:1"

VIDEO_RATIO_MAP: Final[dict[str, str]] = {
    "1x1": "1:1",
    "16x9": "16:9",
    "9x16": "9:16",
}

VIDEO_RATIOS: Final[tuple[str, ...]] = ("1:1", "16:9", "9:16")


def get_kling_model(key: str) -> KlingModelOption:
    for option in KLING_MODELS:
        if option.key == key:
            return option
    return KLING_MODELS[0]


def is_kling_model_key(key: str) -> bool:
    return any(option.key == key for option in KLING_MODELS)


def video_cost(model_key: str, duration: int) -> int:
    model = get_kling_model(model_key)
    return model.cost_5s if duration == 5 else model.cost_10s
