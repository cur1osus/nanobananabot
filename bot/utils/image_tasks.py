from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from binascii import Error as B64DecodeError

import aiohttp

from bot.settings import se

logger = logging.getLogger(__name__)


class ImageGenerationError(RuntimeError):
    """Errors raised when image generation request fails."""


class ImageGenerationTimeoutError(ImageGenerationError):
    """Raised when image generation request times out after retries."""


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
        raise ImageGenerationError(
            "Reference image должен быть в base64 data URL формате."
        )

    mime_type = header[5:].split(";", 1)[0] or "image/jpeg"
    return mime_type, b64_data


def _resolve_image_backend() -> tuple[str, str, int]:
    if se.image_backend.provider != "google":
        raise ImageGenerationError(
            "Поддерживается только IMAGE_BACKEND_PROVIDER=google."
        )

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


def _is_imagen_model(model_id: str) -> bool:
    return model_id.startswith("imagen-")


async def _request_google_json(
    *,
    session: aiohttp.ClientSession,
    url: str,
    api_key: str,
    payload: dict[str, object],
    proxy: str | None,
    timeout: int,
    model_id: str,
) -> dict[str, object]:
    attempts = se.image_backend.retries + 1
    request_timeout = aiohttp.ClientTimeout(total=timeout)

    for attempt in range(1, attempts + 1):
        try:
            async with session.post(
                url,
                params={"key": api_key},
                json=payload,
                proxy=proxy,
                timeout=request_timeout,
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

            if not isinstance(data, dict):
                raise ImageGenerationError(f"Некорректный ответ Google API: {data}")
            return data
        except asyncio.TimeoutError as exc:
            if attempt >= attempts:
                raise ImageGenerationTimeoutError(
                    "Таймаут запроса к Google API генерации изображений "
                    f"(model={model_id}, timeout={timeout}s, attempts={attempts})."
                ) from exc

            retry_in = se.image_backend.retry_backoff * attempt
            logger.warning(
                "Google image API timeout: model=%s attempt=%s/%s retry_in=%.1fs",
                model_id,
                attempt,
                attempts,
                retry_in,
            )
            if retry_in > 0:
                await asyncio.sleep(retry_in)

    raise ImageGenerationError("Не удалось выполнить запрос к Google API")


def _decode_base64_image(raw_b64: str, *, provider_name: str) -> bytes:
    try:
        return base64.b64decode(raw_b64)
    except (ValueError, B64DecodeError) as exc:
        raise ImageGenerationError(
            f"{provider_name} вернуло некорректные данные изображения."
        ) from exc


def _extract_gemini_image(data: dict[str, object]) -> bytes:
    candidates = data.get("candidates")
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
                return _decode_base64_image(raw_b64, provider_name="Google API")

    raise ImageGenerationError(f"Нет изображения в ответе Google API: {data}")


def _extract_imagen_image(data: dict[str, object]) -> bytes:
    predictions = data.get("predictions")
    if not isinstance(predictions, list):
        raise ImageGenerationError(f"Некорректный ответ Imagen API: {data}")

    for prediction in predictions:
        if not isinstance(prediction, dict):
            continue
        raw_b64 = prediction.get("bytesBase64Encoded")
        if isinstance(raw_b64, str) and raw_b64:
            return _decode_base64_image(raw_b64, provider_name="Imagen API")

    raise ImageGenerationError(f"Нет изображения в ответе Imagen API: {data}")


async def _generate_image_with_model(
    *,
    model_id: str,
    prompt: str,
    reference_images: list[str] | None,
    api_key: str,
    base_url: str,
    proxy: str | None,
    timeout: int,
) -> bytes:
    if _is_imagen_model(model_id):
        if reference_images:
            raise ImageGenerationError(
                "Эта модель поддерживает только генерацию по тексту без reference image."
            )

        payload: dict[str, object] = {
            "instances": [{"prompt": prompt}],
        }
        url = f"{base_url}/models/{model_id}:predict"

        async with aiohttp.ClientSession() as session:
            data = await _request_google_json(
                session=session,
                url=url,
                api_key=api_key,
                payload=payload,
                proxy=proxy,
                timeout=timeout,
                model_id=model_id,
            )

        return _extract_imagen_image(data)

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

    payload = {
        "contents": [{"role": "user", "parts": user_parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }
    url = f"{base_url}/models/{model_id}:generateContent"

    async with aiohttp.ClientSession() as session:
        data = await _request_google_json(
            session=session,
            url=url,
            api_key=api_key,
            payload=payload,
            proxy=proxy,
            timeout=timeout,
            model_id=model_id,
        )

    return _extract_gemini_image(data)


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

    try:
        return await _generate_image_with_model(
            model_id=model_id,
            prompt=prompt,
            reference_images=reference_images,
            api_key=api_key,
            base_url=base_url,
            proxy=proxy,
            timeout=timeout,
        )
    except ImageGenerationTimeoutError:
        fallback_model = se.image_backend.fallback_model.strip()
        can_fallback = (
            model_id == se.image_backend.edit_model
            and fallback_model
            and fallback_model != model_id
            and not (reference_images and _is_imagen_model(fallback_model))
        )
        if not can_fallback:
            raise

        logger.warning(
            "Image generation timed out for model=%s, fallback to model=%s",
            model_id,
            fallback_model,
        )
        return await _generate_image_with_model(
            model_id=fallback_model,
            prompt=prompt,
            reference_images=reference_images,
            api_key=api_key,
            base_url=base_url,
            proxy=proxy,
            timeout=timeout,
        )


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
