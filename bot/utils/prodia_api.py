from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from bot.settings import se
from bot.utils.http import get_http_session
from bot.utils.image_tasks import (
    ImageGenerationError,
    ImageGenerationTimeoutError,
)

logger = logging.getLogger(__name__)

_JOB_PATH = "/v2/job"

_ACCEPT_FORMAT_MAP: dict[str, str] = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

_prodia_semaphore: asyncio.Semaphore | None = None


def _get_prodia_semaphore() -> asyncio.Semaphore:
    global _prodia_semaphore
    if _prodia_semaphore is None:
        _prodia_semaphore = asyncio.Semaphore(3)
    return _prodia_semaphore


def _build_job_config(
    *,
    model_id: str,
    prompt: str,
    width: int | None,
    height: int | None,
    image_filenames: list[str],
    steps: int | None,
    guidance_scale: float | None,
    loras: list[dict[str, str | float]] | None = None,
) -> dict:
    config: dict = {"prompt": prompt}
    if image_filenames:
        config["images"] = image_filenames
    else:
        # txt2img: задаём размеры из выбранного соотношения сторон.
        if width:
            config["width"] = width
        if height:
            config["height"] = height
    if steps is not None:
        config["steps"] = steps
    if guidance_scale is not None:
        config["guidance_scale"] = guidance_scale
    if loras:
        config["loras"] = [
            lora["model"] if isinstance(lora, dict) else lora for lora in loras
        ]
    return {"type": model_id, "config": config}


async def _parse_error_message(response: aiohttp.ClientResponse) -> str:
    try:
        payload = await response.json(content_type=None)
    except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError):
        text = await response.text()
        return text[:300] if text else f"HTTP {response.status}"
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("message") or payload)[:300]
    return str(payload)[:300]


async def generate_image_prodia(
    *,
    model_id: str,
    prompt: str,
    reference_images: list[bytes] | None = None,
    width: int | None = None,
    height: int | None = None,
    output_format: str = "jpeg",
    steps: int | None = None,
    guidance_scale: float | None = None,
    loras: list[dict[str, str | float]] | None = None,
) -> bytes:
    """Generate image via Prodia /v2/job (synchronous, returns binary image).

    When ``reference_images`` are provided the request is sent as
    ``multipart/form-data`` (img2img). Otherwise a plain JSON body is sent
    (txt2img). Open-weights FLUX dev/klein have no built-in moderation,
    so adult content is allowed.
    """
    if not se.prodia.api_token:
        raise ImageGenerationError("Не настроен токен Prodia (PRODIA_API_TOKEN).")

    refs = reference_images or []
    accept = _ACCEPT_FORMAT_MAP.get(output_format.lower(), "image/jpeg")
    url = f"{se.prodia.base_url}{_JOB_PATH}"
    image_filenames = [f"ref{i}.jpg" for i in range(len(refs))]
    job = _build_job_config(
        model_id=model_id,
        prompt=prompt,
        width=width,
        height=height,
        image_filenames=image_filenames,
        steps=steps,
        guidance_scale=guidance_scale,
        loras=loras,
    )

    headers = {
        "Authorization": f"Bearer {se.prodia.api_token}",
        "Accept": accept,
    }

    logger.info(
        "Prodia image request: model=%s refs=%d accept=%s",
        model_id,
        len(refs),
        accept,
    )

    request_timeout = aiohttp.ClientTimeout(total=se.prodia.timeout)
    max_attempts = se.prodia.rate_limit_retries + 1

    # Общий ClientSession переиспользует пул соединений/TLS — заголовки и таймаут
    # задаём на уровне запроса, чтобы не плодить сессию на каждый вызов.
    session = get_http_session()

    async with _get_prodia_semaphore():
        try:
            async with asyncio.timeout(se.prodia.total_timeout):
                for attempt in range(max_attempts):
                    if refs:
                        form = aiohttp.FormData()
                        form.add_field(
                            "job",
                            json.dumps(job),
                            filename="job.json",
                            content_type="application/json",
                        )
                        for filename, data in zip(image_filenames, refs, strict=True):
                            form.add_field(
                                "input",
                                data,
                                filename=filename,
                                content_type="image/jpeg",
                            )
                        request_ctx = session.post(
                            url, data=form, headers=headers, timeout=request_timeout
                        )
                    else:
                        request_ctx = session.post(
                            url, json=job, headers=headers, timeout=request_timeout
                        )

                    async with request_ctx as response:
                        if response.status == 200:
                            content_type = response.headers.get("Content-Type", "")
                            if content_type.startswith("image/"):
                                return await response.read()
                            # Неожиданно вернулся JSON вместо картинки.
                            message = await _parse_error_message(response)
                            raise ImageGenerationError(
                                f"Prodia вернул не изображение: {message}"
                            )

                        # 429 (rate limit) и 5xx (временные сбои Prodia,
                        # напр. "connection reset by peer" между их бэкендами)
                        # повторяемы — ретраим с backoff.
                        is_retryable = response.status == 429 or response.status >= 500
                        if is_retryable and attempt + 1 < max_attempts:
                            retry_after = response.headers.get("Retry-After")
                            delay = (
                                float(retry_after)
                                if retry_after and retry_after.isdigit()
                                else se.prodia.rate_limit_backoff * (attempt + 1)
                            )
                            logger.warning(
                                "Prodia %d, retry in %.1fs (attempt %d/%d)",
                                response.status,
                                delay,
                                attempt + 1,
                                max_attempts,
                            )
                            await asyncio.sleep(delay)
                            continue

                        message = await _parse_error_message(response)
                        raise ImageGenerationError(
                            f"Ошибка Prodia ({response.status}): {message}"
                        )

                raise ImageGenerationError(
                    "Prodia: исчерпаны попытки из-за загрузки сервиса (429/5xx)."
                )
        except TimeoutError as exc:
            logger.warning(
                "Prodia generation exceeded total timeout: model=%s total_timeout=%ss",
                model_id,
                se.prodia.total_timeout,
            )
            raise ImageGenerationTimeoutError(
                f"Превышено общее время ожидания генерации изображения "
                f"(model={model_id}, total_timeout={se.prodia.total_timeout}s)."
            ) from exc
        except aiohttp.ClientError as exc:
            raise ImageGenerationError(f"Сетевая ошибка Prodia: {exc}") from exc
