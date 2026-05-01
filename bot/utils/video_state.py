from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiogram.fsm.context import FSMContext

from bot.utils.video_models import (
    DEFAULT_KLING_MODEL_KEY,
    DEFAULT_VIDEO_DURATION,
    DEFAULT_VIDEO_RATIO,
    get_kling_model,
    video_cost,
)

VIDEO_STATE_KEY = "video_flow"


@dataclass
class VideoFlowData:
    model_key: str = DEFAULT_KLING_MODEL_KEY
    duration: int = DEFAULT_VIDEO_DURATION
    aspect_ratio: str = DEFAULT_VIDEO_RATIO
    with_audio: bool = True
    prompt: str = ""
    image_file_id: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VideoFlowData":
        return cls(
            model_key=str(raw.get("model_key", DEFAULT_KLING_MODEL_KEY)),
            duration=int(raw.get("duration", DEFAULT_VIDEO_DURATION)),
            aspect_ratio=str(raw.get("aspect_ratio", DEFAULT_VIDEO_RATIO)),
            with_audio=bool(raw.get("with_audio", True)),
            prompt=str(raw.get("prompt", "")),
            image_file_id=str(raw.get("image_file_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "duration": self.duration,
            "aspect_ratio": self.aspect_ratio,
            "with_audio": self.with_audio,
            "prompt": self.prompt,
            "image_file_id": self.image_file_id,
        }


async def get_video_data(state: FSMContext) -> VideoFlowData:
    data = await state.get_data()
    raw = data.get(VIDEO_STATE_KEY)
    if not isinstance(raw, dict):
        raw = {}
    return VideoFlowData.from_dict(raw)


async def set_video_data(state: FSMContext, data: VideoFlowData) -> None:
    await state.update_data({VIDEO_STATE_KEY: data.to_dict()})


async def update_video_data(state: FSMContext, **kwargs: Any) -> VideoFlowData:
    data = await get_video_data(state)
    for key, value in kwargs.items():
        if hasattr(data, key):
            setattr(data, key, value)
    await set_video_data(state, data)
    return data


def video_settings_text(data: VideoFlowData) -> str:
    prompt_display = data.prompt[:60] + "..." if len(data.prompt) > 60 else data.prompt
    prompt_line = prompt_display if data.prompt else "не указан"
    image_line = "добавлено ✅" if data.image_file_id else "не добавлено"
    model = get_kling_model(data.model_key)
    cost = video_cost(data.model_key, data.duration)
    return (
        "В этом разделе нужно задать настройки для видео, которое будет сгенерировано с помощью Kling:\n\n"
        "1. Опишите видео в разделе «Промпт»\n"
        "2. Можете добавить изображение: оно станет основой для видео\n"
        "3. Выберите продолжительность (5 или 10 сек.) и формат (1:1, 16:9 или 9:16)\n\n"
        f"📝 <b>Текущий промпт:</b> {prompt_line}\n"
        f"🌅 <b>Изображение:</b> {image_line}\n"
        f"💰 <b>Стоимость:</b> {cost} кредитов ({model.title}, {data.duration} сек.)"
    )
