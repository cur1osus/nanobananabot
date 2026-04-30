from __future__ import annotations

import asyncio
import logging

import aiohttp
from runware import IImageInference, Runware

from bot.settings import se

logger = logging.getLogger(__name__)

ASPECT_RATIO_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "3:2": (1248, 832),
    "2:3": (832, 1248),
    "4:3": (1184, 864),
    "3:4": (864, 1184),
    "5:4": (1152, 896),
    "4:5": (896, 1152),
    "16:9": (1344, 768),
    "9:16": (768, 1344),
    "21:9": (1536, 672),
    "auto": (1024, 1024),
}

_OUTPUT_FORMAT_MAP: dict[str, str] = {
    "jpeg": "JPG",
    "jpg": "JPG",
    "png": "PNG",
    "webp": "WEBP",
}

_runware_semaphore: asyncio.Semaphore | None = None
_runware_client: Runware | None = None


def _get_runware_semaphore() -> asyncio.Semaphore:
    global _runware_semaphore
    if _runware_semaphore is None:
        _runware_semaphore = asyncio.Semaphore(3)
    return _runware_semaphore


async def _get_runware_client() -> Runware:
    global _runware_client
    if _runware_client is None:
        _runware_client = Runware(
            api_key=se.image_backend.api_key,
            timeout=se.image_backend.timeout * 1000,
            max_retries=se.image_backend.rate_limit_retries,
            retry_delay=int(se.image_backend.rate_limit_backoff),
        )
    if not _runware_client.connected():
        await _runware_client.connect()
    return _runware_client


class ImageGenerationError(RuntimeError):
    """Errors raised when image generation request fails."""


class ImageGenerationTimeoutError(ImageGenerationError):
    """Raised when image generation request times out after retries."""


def _aspect_ratio_to_dims(aspect_ratio: str) -> tuple[int, int]:
    return ASPECT_RATIO_DIMS.get(aspect_ratio, ASPECT_RATIO_DIMS["1:1"])


async def _download_image(url: str, *, timeout: int) -> bytes:
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=request_timeout) as response:
            if response.status >= 400:
                raise ImageGenerationError(
                    f"Не удалось скачать изображение Runware ({response.status})"
                )
            return await response.read()


async def generate_image(
    prompt: str,
    photo_ids: list[str] | None = None,
    model: str | None = None,
    reference_images: list[str] | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> bytes:
    """Generate image via Runware SDK."""
    del photo_ids

    if se.image_backend.provider != "runware":
        raise ImageGenerationError(
            "Поддерживается только IMAGE_BACKEND_PROVIDER=runware."
        )
    if not se.image_backend.api_key:
        raise ImageGenerationError(
            "Не настроен ключ API для генерации изображений (IMAGE_BACKEND_API_KEY)."
        )

    model_id = model or se.image_backend.model
    width, height = _aspect_ratio_to_dims(aspect_ratio)
    fmt = _OUTPUT_FORMAT_MAP.get(output_format.lower(), "JPG")

    logger.info(
        "Image generation request: provider=runware model=%s refs=%s dims=%dx%d",
        model_id,
        len(reference_images or []),
        width,
        height,
    )

    request = IImageInference(
        model=model_id,
        positivePrompt=prompt,
        width=width,
        height=height,
        outputType="URL",
        outputFormat=fmt,
        numberResults=1,
        referenceImages=reference_images or [],
    )

    async with _get_runware_semaphore():
        try:
            async with asyncio.timeout(se.image_backend.total_timeout):
                client = await _get_runware_client()
                try:
                    images = await client.imageInference(requestImage=request)
                except Exception as exc:
                    raise ImageGenerationError(f"Ошибка Runware SDK: {exc}") from exc

                if not images:
                    raise ImageGenerationError(
                        f"Runware SDK не вернул изображений (model={model_id})"
                    )

                image_url = images[0].imageURL
                if not isinstance(image_url, str) or not image_url:
                    raise ImageGenerationError(
                        f"Runware SDK не вернул imageURL (model={model_id}): {images[0]}"
                    )

                return await _download_image(
                    image_url,
                    timeout=se.image_backend.timeout,
                )
        except TimeoutError as exc:
            logger.warning(
                "Image generation exceeded total timeout: model=%s total_timeout=%ss",
                model_id,
                se.image_backend.total_timeout,
            )
            raise ImageGenerationTimeoutError(
                f"Превышено общее время ожидания генерации изображения "
                f"(model={model_id}, total_timeout={se.image_backend.total_timeout}s)."
            ) from exc
