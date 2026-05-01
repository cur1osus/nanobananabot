from __future__ import annotations

import asyncio
import logging
import uuid

import aiohttp

from bot.settings import se

logger = logging.getLogger(__name__)

RUNWARE_API_URL = "https://api.runware.ai/v1"
_video_semaphore: asyncio.Semaphore | None = None


def _get_video_semaphore() -> asyncio.Semaphore:
    global _video_semaphore
    if _video_semaphore is None:
        _video_semaphore = asyncio.Semaphore(2)
    return _video_semaphore


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
) -> bytes:
    """Generate video via Runware Kling REST API."""
    if not se.image_backend.api_key:
        raise VideoGenerationError(
            "Не настроен ключ API (IMAGE_BACKEND_API_KEY)."
        )

    task_uuid = str(uuid.uuid4())
    task: dict = {
        "taskType": "videoInference",
        "taskUUID": task_uuid,
        "model": runware_model,
        "positivePrompt": prompt,
        "duration": duration,
        "ratio": aspect_ratio,
        "generateAudio": with_audio,
        "numberResults": 1,
    }
    if reference_image:
        task["referenceImage"] = reference_image

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {se.image_backend.api_key}",
    }

    logger.info(
        "Video generation request: model=%s duration=%ds ratio=%s audio=%s",
        runware_model,
        duration,
        aspect_ratio,
        with_audio,
    )

    total_timeout = max(se.image_backend.total_timeout, 300)

    async with _get_video_semaphore():
        try:
            async with asyncio.timeout(total_timeout):
                request_timeout = aiohttp.ClientTimeout(total=total_timeout)
                async with aiohttp.ClientSession(timeout=request_timeout) as session:
                    async with session.post(
                        RUNWARE_API_URL,
                        json=[task],
                        headers=headers,
                    ) as response:
                        if response.status >= 400:
                            body = await response.text()
                            raise VideoGenerationError(
                                f"Runware API вернул {response.status}: {body[:300]}"
                            )
                        result = await response.json()

                if not isinstance(result, list) or not result:
                    raise VideoGenerationError(
                        f"Runware API вернул неожиданный ответ: {result}"
                    )

                item = result[0]
                if item.get("taskType") == "error":
                    raise VideoGenerationError(
                        f"Runware API ошибка: {item.get('message', item)}"
                    )

                video_url = item.get("videoURL") or item.get("url")
                if not video_url:
                    raise VideoGenerationError(
                        f"Runware API не вернул videoURL: {item}"
                    )

                return await _download_video(video_url, timeout=120)

        except TimeoutError as exc:
            raise VideoGenerationTimeoutError(
                f"Превышено время ожидания генерации видео "
                f"(model={runware_model}, timeout={total_timeout}s)."
            ) from exc
