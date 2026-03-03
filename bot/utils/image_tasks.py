from __future__ import annotations

import base64
import logging
import uuid
from binascii import Error as B64DecodeError

import aiohttp

from bot.settings import se

logger = logging.getLogger(__name__)


class ImageGenerationError(RuntimeError):
    """Errors raised when image generation request fails."""


def _resolve_image_backend() -> tuple[str, str, int]:
    if se.image_backend.api_key:
        return (
            se.image_backend.api_key,
            se.image_backend.base_url.rstrip("/"),
            se.image_backend.timeout,
        )

    if se.vsegpt.api_key:
        return (
            se.vsegpt.api_key,
            se.vsegpt.base_url.rstrip("/"),
            se.vsegpt.timeout,
        )

    raise ImageGenerationError(
        "Не настроен ключ API для генерации изображений "
        "(IMAGE_BACKEND_API_KEY или VSEGPT_API_KEY)."
    )


def _resolve_image_proxy() -> str | None:
    proxy = se.image_backend.proxy_url.strip()
    return proxy or None


def _extract_error_message(raw_text: str) -> str:
    text = raw_text.strip()
    if not text:
        return "empty response body"
    return text[:500]


async def generate_image(
    prompt: str,
    photo_ids: list[str] | None = None,
    model: str | None = None,
    reference_images: list[str] | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> bytes:
    """Generate image using VseGPT-compatible images API."""
    del photo_ids

    api_key, base_url, timeout = _resolve_image_backend()
    proxy = _resolve_image_proxy()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    model_id = model or (
        se.image_backend.edit_model if reference_images else se.image_backend.model
    )

    payload: dict[str, str] = {
        "model": model_id,
        "prompt": prompt,
        "response_format": "b64_json",
        "aspect_ratio": aspect_ratio,
        "output_format": output_format,
    }

    if reference_images:
        for idx, image_data_url in enumerate(reference_images[:10], start=1):
            key = "image_url" if idx == 1 else f"image{idx}_url"
            payload[key] = image_data_url

    logger.info(
        "Image generation request: model=%s refs=%s proxy=%s",
        model_id,
        len(reference_images or []),
        bool(proxy),
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/images/generations",
                headers=headers,
                json=payload,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status >= 400:
                    error_text = _extract_error_message(await response.text())
                    logger.error(
                        "Image API request failed: status=%s model=%s body=%s",
                        response.status,
                        payload["model"],
                        error_text,
                    )
                    raise ImageGenerationError(
                        "Ошибка API генерации изображений "
                        f"({response.status}): {error_text}"
                    )

                data = await response.json(content_type=None)
                items = data.get("data") if isinstance(data, dict) else None
                if isinstance(items, list) and items:
                    first = items[0] if isinstance(items[0], dict) else {}
                    b64_image = first.get("b64_json", "")
                    if isinstance(b64_image, str) and b64_image:
                        try:
                            return base64.b64decode(b64_image)
                        except (ValueError, B64DecodeError) as exc:
                            raise ImageGenerationError(
                                "API вернуло некорректные данные изображения."
                            ) from exc

                raise ImageGenerationError(f"Нет изображения в ответе API: {data}")
    except aiohttp.ClientError as exc:
        raise ImageGenerationError(
            f"Сетевая ошибка при запросе к API генерации: {exc}"
        ) from exc


async def enqueue_fake_image_task(
    *,
    model_key: str,
    prompt: str,
    photo_ids: list[str],
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> str:
    """Generate image using VseGPT API (legacy function)."""
    task_id = uuid.uuid4().hex[:10]

    try:
        image_bytes = await generate_image(
            prompt=prompt,
            photo_ids=photo_ids,
            aspect_ratio=aspect_ratio,
            output_format=output_format,
        )
        logger.info(
            "Image generated successfully: task_id=%s model=%s bytes=%s",
            task_id,
            model_key,
            len(image_bytes),
        )
    except Exception as e:
        logger.error("Image generation error: %s", e, exc_info=True)
        raise

    return task_id
