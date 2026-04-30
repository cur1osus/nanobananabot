from __future__ import annotations

import asyncio
import logging
import uuid

import aiohttp

from bot.settings import se
from bot.utils.http_client import (
    ProxySettings,
    create_client_session,
    resolve_proxy_settings,
)

logger = logging.getLogger(__name__)

ASPECT_RATIO_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "3:2": (1264, 848),
    "2:3": (848, 1264),
    "4:3": (1200, 896),
    "3:4": (896, 1200),
    "5:4": (1152, 928),
    "4:5": (928, 1152),
    "16:9": (1264, 848),
    "9:16": (848, 1264),
    "21:9": (1264, 848),
    "auto": (1024, 1024),
}

_OUTPUT_FORMAT_MAP: dict[str, str] = {
    "jpeg": "JPG",
    "jpg": "JPG",
    "png": "PNG",
    "webp": "WEBP",
}

_runware_semaphore: asyncio.Semaphore | None = None


def _get_runware_semaphore() -> asyncio.Semaphore:
    global _runware_semaphore
    if _runware_semaphore is None:
        _runware_semaphore = asyncio.Semaphore(3)
    return _runware_semaphore


class ImageGenerationError(RuntimeError):
    """Errors raised when image generation request fails."""


class ImageGenerationTimeoutError(ImageGenerationError):
    """Raised when image generation request times out after retries."""


def _extract_error_message(raw_text: str) -> str:
    text = raw_text.strip()
    return text[:500] if text else "empty response body"


def _resolve_image_backend() -> tuple[str, str, int]:
    if se.image_backend.provider != "runware":
        raise ImageGenerationError(
            "Поддерживается только IMAGE_BACKEND_PROVIDER=runware."
        )
    if not se.image_backend.api_key:
        raise ImageGenerationError(
            "Не настроен ключ API для генерации изображений (IMAGE_BACKEND_API_KEY)."
        )
    base_url = se.image_backend.base_url.rstrip("/")
    return se.image_backend.api_key, base_url, se.image_backend.timeout


def _resolve_image_proxy_settings() -> ProxySettings:
    return resolve_proxy_settings(se.image_backend.proxy_url)


def _aspect_ratio_to_dims(aspect_ratio: str) -> tuple[int, int]:
    return ASPECT_RATIO_DIMS.get(aspect_ratio, ASPECT_RATIO_DIMS["1:1"])


def _build_task(
    *,
    model_id: str,
    prompt: str,
    reference_images: list[str] | None,
    width: int,
    height: int,
    output_format: str,
) -> dict[str, object]:
    task: dict[str, object] = {
        "taskType": "imageInference",
        "taskUUID": str(uuid.uuid4()),
        "model": model_id,
        "positivePrompt": prompt,
        "width": width,
        "height": height,
        "outputType": "URL",
        "outputFormat": output_format,
    }
    if reference_images:
        task["inputs"] = {"referenceImages": reference_images}
    return task


async def _download_image(url: str, *, session: aiohttp.ClientSession, proxy: str | None, timeout: int) -> bytes:
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    async with session.get(url, proxy=proxy, timeout=request_timeout) as response:
        if response.status >= 400:
            raise ImageGenerationError(f"Не удалось скачать изображение Runware ({response.status})")
        return await response.read()


async def _request_runware(
    *,
    session: aiohttp.ClientSession,
    api_key: str,
    endpoint: str,
    task: dict[str, object],
    proxy: str | None,
    timeout: int,
    model_id: str,
) -> dict[str, object]:
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    attempts = se.image_backend.retries + 1

    for attempt in range(1, attempts + 1):
        try:
            rate_attempt = 0
            while True:
                async with session.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=[task],
                    proxy=proxy,
                    timeout=request_timeout,
                ) as response:
                    if response.status == 429:
                        if rate_attempt >= se.image_backend.rate_limit_retries:
                            error_text = _extract_error_message(await response.text())
                            logger.error(
                                "Runware API rate limit exhausted: model=%s body=%s",
                                model_id,
                                error_text,
                            )
                            raise ImageGenerationError(
                                f"Ошибка Runware API (429): {error_text}"
                            )
                        rate_attempt += 1
                        wait = se.image_backend.rate_limit_backoff * (2 ** (rate_attempt - 1))
                        logger.warning(
                            "Runware API rate limited (429): model=%s rate_attempt=%s/%s retry_in=%.1fs",
                            model_id,
                            rate_attempt,
                            se.image_backend.rate_limit_retries,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                    if response.status >= 400:
                        error_text = _extract_error_message(await response.text())
                        logger.error(
                            "Runware API request failed: status=%s model=%s body=%s",
                            response.status,
                            model_id,
                            error_text,
                        )
                        raise ImageGenerationError(
                            f"Ошибка Runware API ({response.status}): {error_text}"
                        )

                    data = await response.json(content_type=None)
                    break

            if not isinstance(data, dict):
                raise ImageGenerationError(f"Некорректный ответ Runware API: {data}")

            results = data.get("data")
            if not isinstance(results, list) or not results:
                raise ImageGenerationError(f"Пустой ответ Runware API: {data}")

            result = results[0]
            if not isinstance(result, dict):
                raise ImageGenerationError(f"Некорректный результат Runware API: {result}")

            return result

        except asyncio.TimeoutError as exc:
            if attempt >= attempts:
                raise ImageGenerationTimeoutError(
                    f"Таймаут запроса к Runware API "
                    f"(model={model_id}, timeout={timeout}s, attempts={attempts})."
                ) from exc

            retry_in = se.image_backend.retry_backoff * attempt
            logger.warning(
                "Runware API timeout: model=%s attempt=%s/%s retry_in=%.1fs",
                model_id,
                attempt,
                attempts,
                retry_in,
            )
            if retry_in > 0:
                await asyncio.sleep(retry_in)

    raise ImageGenerationError("Не удалось выполнить запрос к Runware API")


async def generate_image(
    prompt: str,
    photo_ids: list[str] | None = None,
    model: str | None = None,
    reference_images: list[str] | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> bytes:
    """Generate image via Runware API."""
    del photo_ids

    api_key, base_url, timeout = _resolve_image_backend()
    proxy_settings = _resolve_image_proxy_settings()

    model_id = model or se.image_backend.model
    width, height = _aspect_ratio_to_dims(aspect_ratio)
    fmt = _OUTPUT_FORMAT_MAP.get(output_format.lower(), "JPG")

    logger.info(
        "Image generation request: provider=runware model=%s refs=%s dims=%dx%d proxy=%s",
        model_id,
        len(reference_images or []),
        width,
        height,
        proxy_settings.source,
    )

    task = _build_task(
        model_id=model_id,
        prompt=prompt,
        reference_images=reference_images,
        width=width,
        height=height,
        output_format=fmt,
    )
    endpoint = f"{base_url}/inference"

    async with _get_runware_semaphore():
        try:
            async with asyncio.timeout(se.image_backend.total_timeout):
                async with create_client_session(proxy_settings=proxy_settings) as session:
                    result = await _request_runware(
                        session=session,
                        api_key=api_key,
                        endpoint=endpoint,
                        task=task,
                        proxy=proxy_settings.explicit_proxy,
                        timeout=timeout,
                        model_id=model_id,
                    )
                    image_url = result.get("imageURL")
                    if not isinstance(image_url, str) or not image_url:
                        raise ImageGenerationError(
                            f"Runware API не вернул imageURL (model={model_id}): {result}"
                        )
                    return await _download_image(
                        image_url,
                        session=session,
                        proxy=proxy_settings.explicit_proxy,
                        timeout=timeout,
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
