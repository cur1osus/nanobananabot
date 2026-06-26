from __future__ import annotations

from typing import Any

from bot.handlers.menu.tracks import _extract_tracks
from bot.keyboards.inline import ik_main
from bot.utils.background_task_helpers import send_tracks
from bot.utils.suno_api import SunoClient


async def test_main_keyboard_contains_music_sections() -> None:
    markup = await ik_main(is_admin=False)
    callback_data = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]

    assert "menu:music" in callback_data
    assert "menu:tracks" in callback_data


def test_extract_tracks_accepts_suno_response_formats() -> None:
    suno_data_track = {"id": "from-sunoData"}
    data_track = {"id": "from-data"}

    assert _extract_tracks({"response": {"sunoData": [suno_data_track]}}) == [
        suno_data_track
    ]
    assert _extract_tracks({"response": {"data": [data_track]}}) == [data_track]


async def test_send_tracks_without_tracks_returns_empty_list() -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.messages: list[tuple[int, str]] = []

        async def send_message(self, chat_id: int, text: str) -> None:
            self.messages.append((chat_id, text))

    bot = FakeBot()

    file_ids = await send_tracks(
        bot,
        chat_id=123,
        filename_base="empty",
        data={"response": {}},
    )

    assert file_ids == []
    assert bot.messages == [(123, "Готово, но ссылки на аудио не получены.")]


async def test_suno_generate_music_uses_sunobot_api_payload() -> None:
    class FakeSunoClient(SunoClient):
        def __init__(self) -> None:
            super().__init__(
                api_key="test-key",
                callback_url="https://example.com/callback",
                default_model="V5",
            )
            self.last_request: dict[str, Any] | None = None

        async def _request(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, Any] | None = None,
            params: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            self.last_request = {
                "method": method,
                "path": path,
                "payload": payload,
                "params": params,
            }
            return {"data": {"taskId": "task-123"}}

    client = FakeSunoClient()
    task_id = await client.generate_music(
        prompt="lyrics",
        custom_mode=True,
        instrumental=False,
        style="Pop",
        title="Song",
    )

    assert task_id == "task-123"
    assert client.last_request == {
        "method": "POST",
        "path": "/api/v1/generate",
        "payload": {
            "prompt": "lyrics",
            "style": "Pop",
            "title": "Song",
            "customMode": True,
            "instrumental": False,
            "callBackUrl": "https://example.com/callback",
            "model": "V5",
        },
        "params": None,
    }
