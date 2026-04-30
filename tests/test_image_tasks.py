from __future__ import annotations

import asyncio

import pytest

from bot.settings import se
from bot.utils.image_tasks import ImageGenerationTimeoutError, generate_image


async def test_generate_image_respects_total_timeout(monkeypatch) -> None:
    original_total_timeout = se.image_backend.total_timeout

    async def fake_request_runware(**_: object) -> dict:
        await asyncio.sleep(2)
        return {"imageURL": "https://example.invalid/image.jpg"}

    monkeypatch.setattr(se.image_backend, "total_timeout", 1)
    monkeypatch.setattr(se.image_backend, "provider", "runware")
    monkeypatch.setattr(se.image_backend, "api_key", "test-key")
    monkeypatch.setattr(
        "bot.utils.image_tasks._request_runware",
        fake_request_runware,
    )

    with pytest.raises(ImageGenerationTimeoutError):
        await generate_image(prompt="test", model="google:4@1")

    monkeypatch.setattr(se.image_backend, "total_timeout", original_total_timeout)
