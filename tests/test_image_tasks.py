from __future__ import annotations

import asyncio

import pytest

from bot.settings import se
from bot.utils.image_tasks import ImageGenerationTimeoutError, generate_image


async def test_generate_image_respects_total_timeout(monkeypatch) -> None:
    class _FakeImage:
        imageURL = "https://example.invalid/image.jpg"

    class _FakeRunware:
        def connected(self) -> bool:
            return True

        async def connect(self) -> None:
            pass

        async def imageInference(self, **_: object) -> list:
            await asyncio.sleep(2)
            return [_FakeImage()]

    async def fake_get_client() -> _FakeRunware:
        return _FakeRunware()

    monkeypatch.setattr(se.image_backend, "total_timeout", 1)
    monkeypatch.setattr(se.image_backend, "provider", "runware")
    monkeypatch.setattr(se.image_backend, "api_key", "test-key")
    monkeypatch.setattr("bot.utils.image_tasks._get_runware_client", fake_get_client)

    with pytest.raises(ImageGenerationTimeoutError):
        await generate_image(prompt="test", model="google:4@1")
