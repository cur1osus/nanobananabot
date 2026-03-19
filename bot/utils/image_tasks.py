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


def _extract_error_message(raw_text: str) -> str:
    text = raw_text.strip()
    if not text:
        return "empty response body"
    return text[:500]


def _parse_data_url(data_url: str) -> tuple[str, str]:
    # data:image/jpeg;base64,<base64>
    if not data_url.startswith("data:") or "," not in data_url:
        raise ImageGenerationError(
            "Некорректный формат reference image (ожидается data URL)."
        )

    header, b64_data = data_url.split(",", 1)
    if ";base64" not in header:
        raise ImageGenerationError("Reference image должен быть в base64 data URL формате.")

    mime_type = header[5:].split(";", 1)[0] or "image/jpeg"
    return mime_type, b64_data


def _resolve_image_backend() -> tuple[str, str, int]:
    if se.image_backend.provider != "google":
        raise ImageGenerationError("Поддерживается только IMAGE_BACKEND_PROVIDER=google.")

    if not se.image_backend.api_key:
        raise ImageGenerationError(
            "Не настроен ключ API для генерации изображений (IMAGE_BACKEND_API_KEY)."
        )

    return (
        se.image_backend.api_key,
        se.image_backend.base_url.rstrip("/"),
        se.image_backend.timeout,
    )


def _resolve_image_proxy() -> str | None:
    proxy = se.image_backend.proxy_url.strip()
    return proxy or None


async def generate_image(
    prompt: str,
    photo_ids: list[str] | None = None,
    model: str | None = None,
    reference_images: list[str] | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> bytes:
    """Generate or edit image via Google Generative Language API."""
    del photo_ids
    del aspect_ratio
    del output_format

    api_key, base_url, timeout = _resolve_image_backend()
    proxy = _resolve_image_proxy()

    model_id = model or (
        se.image_backend.edit_model if reference_images else se.image_backend.model
    )

    logger.info(
        "Image generation request: provider=google model=%s refs=%s proxy=%s",
        model_id,
        len(reference_images or []),
        bool(proxy),
    )

    user_parts: list[dict[str, object]] = [{"text": prompt}]

    for image_data_url in reference_images or []:
        mime_type, b64_data = _parse_data_url(image_data_url)
        user_parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": b64_data,
                }
            }
        )

    payload: dict[str, object] = {
        "contents": [{"role": "user", "parts": user_parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }

    url = f"{base_url}/models/{model_id}:generateContent"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            params={"key": api_key},
            json=payload,
            proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            if response.status >= 400:
                error_text = _extract_error_message(await response.text())
                logger.error(
                    "Google image API request failed: status=%s model=%s body=%s",
                    response.status,
                    model_id,
                    error_text,
                )
                raise ImageGenerationError(
                    "Ошибка Google API генерации изображений "
                    f"({response.status}): {error_text}"
                )

            data = await response.json(content_type=None)

    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(candidates, list):
        raise ImageGenerationError(f"Некорректный ответ Google API: {data}")

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict):
                continue
            raw_b64 = inline.get("data")
            if isinstance(raw_b64, str) and raw_b64:
                try:
                    return base64.b64decode(raw_b64)
                except (ValueError, B64DecodeError) as exc:
                    raise ImageGenerationError(
                        "Google API вернуло некорректные данные изображения."
                    ) from exc

    raise ImageGenerationError(f"Нет изображения в ответе Google API: {data}")


async def enqueue_fake_image_task(
    *,
    model_key: str,
    prompt: str,
    photo_ids: list[str],
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> str:
    """Generate image and return fake task id (legacy helper)."""
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
