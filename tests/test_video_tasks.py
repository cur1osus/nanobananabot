from __future__ import annotations

import pytest

from bot.keyboards.inline import ik_video_settings
from bot.settings import se
from bot.utils.video_models import get_kling_model, video_cost
from bot.utils.video_tasks import generate_video


class _FakeVideoStart:
    taskUUID = "task-uuid"


class _FakeVideoResult:
    videoURL = "https://example.invalid/video.mp4"


async def test_kling_26_i2v_uses_frame_images(monkeypatch) -> None:
    model = get_kling_model("2.6")
    captured_requests = []

    class _FakeRunware:
        def connected(self) -> bool:
            return True

        async def connect(self) -> None:
            pass

        async def videoInference(self, *, requestVideo: object) -> _FakeVideoStart:
            captured_requests.append(requestVideo)
            return _FakeVideoStart()

        async def getResponse(self, *, taskUUID: str, numberResults: int) -> list:
            assert taskUUID == "task-uuid"
            assert numberResults == 1
            return [_FakeVideoResult()]

    async def fake_get_client() -> _FakeRunware:
        return _FakeRunware()

    async def fake_download_video(url: str, *, timeout: int) -> bytes:
        assert url == "https://example.invalid/video.mp4"
        assert timeout == 120
        return b"video-bytes"

    monkeypatch.setattr(se.image_backend, "api_key", "test-key")
    monkeypatch.setattr("bot.utils.video_tasks._get_video_client", fake_get_client)
    monkeypatch.setattr("bot.utils.video_tasks._download_video", fake_download_video)

    result = await generate_video(
        prompt="test",
        runware_model=model.runware_model,
        duration=10,
        aspect_ratio="16:9",
        with_audio=True,
        reference_image="data:image/jpeg;base64,test",
        supports_duration=model.supports_duration,
        supports_dimensions=model.supports_dimensions,
        supports_sound=model.supports_sound,
        ratio_dims=model.ratio_dims,
        needs_provider_settings=model.needs_provider_settings,
    )

    assert result == b"video-bytes"
    assert len(captured_requests) == 1

    request = captured_requests[0]
    assert request.model == "klingai:kling-video@2.6-pro"
    assert request.duration == 10
    assert request.width is None
    assert request.height is None
    assert request.inputs is not None
    assert request.inputs.referenceImages is None
    assert len(request.inputs.frameImages) == 1
    assert request.inputs.frameImages[0].image == "data:image/jpeg;base64,test"
    assert request.inputs.frameImages[0].frame == "first"
    assert request.providerSettings.characterOrientation == "image"
    assert request.providerSettings.sound is None


@pytest.mark.parametrize("with_audio", [True, False])
async def test_kling_26_t2v_uses_model_specific_dimensions_and_sound_toggle(
    monkeypatch,
    with_audio: bool,
) -> None:
    model = get_kling_model("2.6")
    captured_requests = []

    class _FakeRunware:
        def connected(self) -> bool:
            return True

        async def connect(self) -> None:
            pass

        async def videoInference(self, *, requestVideo: object) -> _FakeVideoStart:
            captured_requests.append(requestVideo)
            return _FakeVideoStart()

        async def getResponse(self, *, taskUUID: str, numberResults: int) -> list:
            return [_FakeVideoResult()]

    async def fake_get_client() -> _FakeRunware:
        return _FakeRunware()

    async def fake_download_video(url: str, *, timeout: int) -> bytes:
        return b"video-bytes"

    monkeypatch.setattr(se.image_backend, "api_key", "test-key")
    monkeypatch.setattr("bot.utils.video_tasks._get_video_client", fake_get_client)
    monkeypatch.setattr("bot.utils.video_tasks._download_video", fake_download_video)

    result = await generate_video(
        prompt="test",
        runware_model=model.runware_model,
        duration=5,
        aspect_ratio="1:1",
        with_audio=with_audio,
        reference_image=None,
        supports_duration=model.supports_duration,
        supports_dimensions=model.supports_dimensions,
        supports_sound=model.supports_sound,
        ratio_dims=model.ratio_dims,
        needs_provider_settings=model.needs_provider_settings,
    )

    assert result == b"video-bytes"
    assert len(captured_requests) == 1

    request = captured_requests[0]
    assert request.duration == 5
    assert request.width == 1080
    assert request.height == 1080
    assert request.inputs is None
    assert request.providerSettings.sound is with_audio


async def test_video_settings_hide_sound_toggle_for_image_to_video() -> None:
    keyboard = await ik_video_settings(
        model_key="2.6",
        duration=5,
        aspect_ratio="1:1",
        with_audio=True,
        has_image=True,
    )

    texts = [button.text for row in keyboard.inline_keyboard for button in row]

    assert "✅ Со звуком" not in texts
    assert "Без звука" not in texts


def test_kling_26_supports_ten_second_pricing() -> None:
    model = get_kling_model("2.6")

    assert model.supports_duration is True
    assert video_cost("2.6", 5) == 25
    assert video_cost("2.6", 10) == 45


def test_video_ratio_dimensions_are_immutable() -> None:
    model = get_kling_model("2.6")

    with pytest.raises(TypeError):
        model.ratio_dims["1:1"] = (1, 1)
