from __future__ import annotations

import asyncio
import logging

import aiohttp
from runware import IFrameImage, IKlingAIProviderSettings, IVideoInference, Runware

from bot.settings import se
from bot.utils.video_models import VIDEO_RATIO_DIMS

logger = logging.getLogger(__name__)

_video_semaphore: asyncio.Semaphore | None = None
_video_client: Runware | None = None


def _get_video_semaphore() -> asyncio.Semaphore:
    global _video_semaphore
    if _video_semaphore is None:
        _video_semaphore = asyncio.Semaphore(2)
    return _video_semaphore


async def _get_video_client() -> Runware:
    global _video_client
    total_timeout_ms = max(se.image_backend.total_timeout, 300) * 1000
    if _video_client is None:
        _video_client = Runware(
            api_key=se.image_backend.api_key,
            timeout=total_timeout_ms,
        )
    if not _video_client.connected():
        await _video_client.connect()
    return _video_client


class VideoGenerationError(RuntimeError):
    """Raised when video generation request fails."""


class VideoGenerationTimeoutError(VideoGenerationError):
    """Raised when video generation times out."""


async def _download_video(url: str, *, timeout: int = 300) -> bytes:
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=request_timeout) as response:
            if response.status >= 400:
                raise VideoGenerationError(
                    f"Не удалось скачать видео Runware ({response.status})"
                )
            return await response.read()


async def generate_video(
    prompt: str,
    runware_model: str,
    duration: int = 5,
    aspect_ratio: str = "1:1",
    with_audio: bool = True,
    reference_image: str | None = None,
    supports_duration: bool = False,
    supports_dimensions: bool = False,
    supports_sound: bool = False,
    image_input_type: str = "frameImages",
    needs_provider_settings: bool = False,
) -> bytes:
    """Generate video via Runware SDK."""
    if not se.image_backend.api_key:
        raise VideoGenerationError(
            "Не настроен ключ API (IMAGE_BACKEND_API_KEY)."
        )

    frame_images: list[IFrameImage] = []
    reference_images: list[str] = []
    provider_settings: IKlingAIProviderSettings | None = None

    if reference_image:
        if image_input_type == "referenceImages":
            reference_images = [reference_image]
        else:
            frame_images = [IFrameImage(inputImage=reference_image, frame="first")]
        if needs_provider_settings:
            provider_settings = IKlingAIProviderSettings(characterOrientation="image")

    request_kwargs: dict = {
        "model": runware_model,
        "positivePrompt": prompt,
        "numberResults": 1,
        "outputType": "URL",
    }
    if supports_duration:
        request_kwargs["duration"] = duration
    if supports_dimensions:
        dims = VIDEO_RATIO_DIMS.get(aspect_ratio, (960, 960))
        request_kwargs["width"] = dims[0]
        request_kwargs["height"] = dims[1]
    if frame_images:
        request_kwargs["frameImages"] = frame_images
    if reference_images:
        request_kwargs["referenceImages"] = reference_images
    if provider_settings:
        request_kwargs["providerSettings"] = provider_settings

    request = IVideoInference(**request_kwargs)

    total_timeout = max(se.image_backend.total_timeout, 300)

    logger.info(
        "Video generation request: model=%s duration=%s ratio=%s image=%s",
        runware_model,
        duration if supports_duration else "fixed",
        aspect_ratio if supports_dimensions else "fixed",
        bool(reference_image),
    )

    async with _get_video_semaphore():
        try:
            async with asyncio.timeout(total_timeout):
                client = await _get_video_client()
                try:
                    videos = await client.videoInference(requestVideo=request)
                except Exception as exc:
                    raise VideoGenerationError(f"Ошибка Runware SDK: {exc}") from exc

                if not videos:
                    raise VideoGenerationError(
                        f"Runware SDK не вернул видео (model={runware_model})"
                    )

                video_url = videos[0].videoURL
                if not isinstance(video_url, str) or not video_url:
                    raise VideoGenerationError(
                        f"Runware SDK не вернул videoURL (model={runware_model}): {videos[0]}"
                    )

                return await _download_video(video_url, timeout=120)

        except TimeoutError as exc:
            raise VideoGenerationTimeoutError(
                f"Превышено время ожидания генерации видео "
                f"(model={runware_model}, timeout={total_timeout}s)."
            ) from exc
