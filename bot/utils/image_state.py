from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiogram.fsm.context import FSMContext

from bot.utils.image_models import DEFAULT_IMAGE_MODEL_KEY

IMAGE_STATE_KEY = "image_flow"


@dataclass
class ImageFlowData:
    model_key: str = DEFAULT_IMAGE_MODEL_KEY
    photos: list[str] = field(default_factory=list)
    aspect_ratio: str = "1:1"
    prompt: str = ""
    prompt_requested: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ImageFlowData":
        model_key = str(raw.get("model_key", DEFAULT_IMAGE_MODEL_KEY))
        raw_photos = raw.get("photos", [])
        photos = (
            [str(item) for item in raw_photos] if isinstance(raw_photos, list) else []
        )
        return cls(
            model_key=model_key,
            photos=photos,
            aspect_ratio=str(raw.get("aspect_ratio", "1:1")) or "1:1",
            prompt=str(raw.get("prompt", "")),
            prompt_requested=bool(raw.get("prompt_requested", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "photos": list(self.photos),
            "aspect_ratio": self.aspect_ratio,
            "prompt": self.prompt,
            "prompt_requested": self.prompt_requested,
        }


async def get_image_data(state: FSMContext) -> ImageFlowData:
    data = await state.get_data()
    raw = data.get(IMAGE_STATE_KEY)
    if not isinstance(raw, dict):
        raw = {}
    return ImageFlowData.from_dict(raw)


async def set_image_data(state: FSMContext, data: ImageFlowData) -> None:
    await state.update_data({IMAGE_STATE_KEY: data.to_dict()})


async def update_image_data(state: FSMContext, **kwargs: Any) -> ImageFlowData:
    data = await get_image_data(state)
    for key, value in kwargs.items():
        if hasattr(data, key):
            setattr(data, key, value)
    await set_image_data(state, data)
    return data
