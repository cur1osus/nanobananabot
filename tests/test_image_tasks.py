from __future__ import annotations

import asyncio

import pytest

from bot.settings import se
from bot.utils.image_tasks import (
    ASPECT_RATIO_DIMS,
    ImageGenerationTimeoutError,
    _bytes_to_data_url,
    generate_image,
)


def test_default_aspect_ratio_dimensions_are_valid_runware_steps() -> None:
    for width, height in ASPECT_RATIO_DIMS.values():
        assert width % 16 == 0
        assert height % 16 == 0


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


@pytest.mark.parametrize(
    "model",
    [
        "alibaba:wan@2.7-image",
        "bfl:7@1",
        "openai:gpt-image@2",
        "runware:400@1",
        "runware:400@2",
    ],
)
async def test_input_reference_models_send_reference_images_inside_inputs(
    monkeypatch,
    model: str,
) -> None:
    class _FakeImage:
        imageURL = "https://example.invalid/image.jpg"

    captured_requests = []

    class _FakeRunware:
        def connected(self) -> bool:
            return True

        async def connect(self) -> None:
            pass

        async def imageInference(self, *, requestImage: object) -> list:
            captured_requests.append(requestImage)
            return [_FakeImage()]

    async def fake_get_client() -> _FakeRunware:
        return _FakeRunware()

    async def fake_download_image(url: str, *, timeout: int) -> bytes:
        return b"image-bytes"

    monkeypatch.setattr(se.image_backend, "provider", "runware")
    monkeypatch.setattr(se.image_backend, "api_key", "test-key")
    monkeypatch.setattr("bot.utils.image_tasks._get_runware_client", fake_get_client)
    monkeypatch.setattr("bot.utils.image_tasks._download_image", fake_download_image)

    result = await generate_image(
        prompt="test",
        model=model,
        reference_images=[b"image-ref-bytes"],
    )

    expected_ref = _bytes_to_data_url(b"image-ref-bytes")
    assert result == b"image-bytes"
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.referenceImages == []
    assert request.inputs is not None
    assert request.inputs.referenceImages == [expected_ref]


async def test_wan27_uses_dimensions_with_documented_minimums(monkeypatch) -> None:
    class _FakeImage:
        imageURL = "https://example.invalid/image.jpg"

    captured_requests = []

    class _FakeRunware:
        def connected(self) -> bool:
            return True

        async def connect(self) -> None:
            pass

        async def imageInference(self, *, requestImage: object) -> list:
            captured_requests.append(requestImage)
            return [_FakeImage()]

    async def fake_get_client() -> _FakeRunware:
        return _FakeRunware()

    async def fake_download_image(url: str, *, timeout: int) -> bytes:
        return b"image-bytes"

    monkeypatch.setattr(se.image_backend, "provider", "runware")
    monkeypatch.setattr(se.image_backend, "api_key", "test-key")
    monkeypatch.setattr("bot.utils.image_tasks._get_runware_client", fake_get_client)
    monkeypatch.setattr("bot.utils.image_tasks._download_image", fake_download_image)

    result = await generate_image(
        prompt="test",
        model="alibaba:wan@2.7-image",
        aspect_ratio="21:9",
    )

    assert result == b"image-bytes"
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.width == 1792
    assert request.height == 768


async def test_default_models_keep_top_level_reference_images(monkeypatch) -> None:
    class _FakeImage:
        imageURL = "https://example.invalid/image.jpg"

    captured_requests = []

    class _FakeRunware:
        def connected(self) -> bool:
            return True

        async def connect(self) -> None:
            pass

        async def imageInference(self, *, requestImage: object) -> list:
            captured_requests.append(requestImage)
            return [_FakeImage()]

    async def fake_get_client() -> _FakeRunware:
        return _FakeRunware()

    async def fake_download_image(url: str, *, timeout: int) -> bytes:
        return b"image-bytes"

    monkeypatch.setattr(se.image_backend, "provider", "runware")
    monkeypatch.setattr(se.image_backend, "api_key", "test-key")
    monkeypatch.setattr("bot.utils.image_tasks._get_runware_client", fake_get_client)
    monkeypatch.setattr("bot.utils.image_tasks._download_image", fake_download_image)

    result = await generate_image(
        prompt="test",
        model="google:4@1",
        reference_images=[b"image-ref-bytes"],
    )

    expected_ref = _bytes_to_data_url(b"image-ref-bytes")
    assert result == b"image-bytes"
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.referenceImages == [expected_ref]
    assert request.inputs is None
