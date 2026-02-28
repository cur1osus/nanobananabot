from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiogram.fsm.context import FSMContext

MUSIC_STATE_KEY = "music_flow"


@dataclass
class MusicFlowData:
    prompt_source: str | None = None
    instrumental: bool = False
    prompt: str = ""
    custom_mode: bool = False
    style: str = ""
    title: str = ""
    topic: str = ""
    title_back_target: str = ""
    prompt_after_mode: bool = False
    prompt_after_title: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MusicFlowData":
        return cls(
            prompt_source=raw.get("prompt_source"),
            instrumental=bool(raw.get("instrumental", False)),
            prompt=str(raw.get("prompt", "")),
            custom_mode=bool(raw.get("custom_mode", False)),
            style=str(raw.get("style", "")),
            title=str(raw.get("title", "")),
            topic=str(raw.get("topic", "")),
            title_back_target=str(raw.get("title_back_target", "")),
            prompt_after_mode=bool(raw.get("prompt_after_mode", False)),
            prompt_after_title=bool(raw.get("prompt_after_title", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_source": self.prompt_source,
            "instrumental": self.instrumental,
            "prompt": self.prompt,
            "custom_mode": self.custom_mode,
            "style": self.style,
            "title": self.title,
            "topic": self.topic,
            "title_back_target": self.title_back_target,
            "prompt_after_mode": self.prompt_after_mode,
            "prompt_after_title": self.prompt_after_title,
        }


async def get_music_data(state: FSMContext) -> MusicFlowData:
    data = await state.get_data()
    raw = data.get(MUSIC_STATE_KEY)
    if not isinstance(raw, dict):
        raw = {}
    return MusicFlowData.from_dict(raw)


async def set_music_data(state: FSMContext, data: MusicFlowData) -> None:
    await state.update_data({MUSIC_STATE_KEY: data.to_dict()})


async def update_music_data(state: FSMContext, **kwargs: Any) -> MusicFlowData:
    data = await get_music_data(state)
    for key, value in kwargs.items():
        if hasattr(data, key):
            setattr(data, key, value)
    await set_music_data(state, data)
    return data
