from __future__ import annotations

import asyncio
import collections.abc
import logging

import aiohttp

from bot.settings import se
from bot.utils.http import get_http_session
from bot.utils.image_tasks import ImageGenerationError, ImageGenerationTimeoutError

logger = logging.getLogger(__name__)

CIVITAI_WORKFLOW_URL = f"{se.civitai.base_url}/v2/consumer/workflows"
CIVITAI_POLL_INTERVAL = 10

_civitai_semaphore: asyncio.Semaphore | None = None


def _get_civitai_semaphore() -> asyncio.Semaphore:
    global _civitai_semaphore
    if _civitai_semaphore is None:
        _civitai_semaphore = asyncio.Semaphore(2)
    return _civitai_semaphore


def _build_workflow_request(
    *,
    prompt: str,
    width: int,
    height: int,
    model_version: str = "9b",
    cfg_scale: float | None = None,
    steps: int | None = None,
    negative_prompt: str | None = None,
    loras: list[dict[str, str | float]] | None = None,
    reference_images: list[str] | None = None,
) -> dict:
    operation = "editImage" if reference_images else "createImage"
    step_input: dict = {
        "engine": "flux2",
        "model": "klein",
        "operation": operation,
        "modelVersion": model_version,
        "prompt": prompt,
        "sampleMethod": "euler",
    }

    if reference_images:
        step_input["images"] = reference_images[:2]
    else:
        step_input["width"] = width
        step_input["height"] = height

    if cfg_scale is not None:
        step_input["cfgScale"] = cfg_scale
    if steps is not None:
        step_input["steps"] = steps
    if negative_prompt:
        step_input["negativePrompt"] = negative_prompt

    if loras:
        step_input["loras"] = {
            str(lora.get("model", "")): float(lora.get("weight", 1.0)) for lora in loras
        }

    return {
        "allowMatureContent": True,
        "steps": [
            {
                "$type": "imageGen",
                "input": step_input,
            }
        ],
    }


async def _download_blob(url: str, auth_key: str) -> bytes | None:
    """Download a Civitai blob URL with auth header fallback."""
    session = get_http_session()
    headers = {"Authorization": f"Bearer {auth_key}"}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.read()
            logger.warning(
                "Blob download failed (%s), retrying without auth", resp.status
            )
            async with session.get(url) as resp2:
                if resp2.status == 200:
                    return await resp2.read()
    except Exception:
        logger.exception("Blob download exception")
    return None


async def generate_image_civitai(
    *,
    prompt: str,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
    negative_prompt: str | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    loras: list[dict[str, str | float]] | None = None,
    reference_images: list[bytes] | None = None,
    on_submit: collections.abc.Callable[[str], collections.abc.Awaitable[None]]
    | None = None,
) -> bytes:
    """Сгенерировать изображение через CivitAI (submit + poll).

    ``on_submit`` вызывается с ``workflow_id`` сразу после успешной отправки
    воркфлоу — это даёт воркеру сохранить id, чтобы при рестарте доопросить
    задачу через :func:`poll_civitai_workflow`, а не отправлять её заново.
    """
    if not se.civitai.api_key:
        raise ImageGenerationError("Не настроен ключ Civitai (CIVITAI_API_KEY).")

    from bot.utils.image_tasks import ASPECT_RATIO_DIMS, _bytes_to_data_url

    ref_urls: list[str] | None = None
    if reference_images:
        ref_urls = [_bytes_to_data_url(img) for img in reference_images]

    if not ref_urls and (not width or not height):
        dims = ASPECT_RATIO_DIMS.get(aspect_ratio, ASPECT_RATIO_DIMS["1:1"])
        width = width or dims[0]
        height = height or dims[1]

    body = _build_workflow_request(
        prompt=prompt,
        width=width or 1024,
        height=height or 1024,
        model_version="9b",
        cfg_scale=cfg_scale,
        steps=steps,
        negative_prompt=negative_prompt,
        loras=loras,
        reference_images=ref_urls,
    )

    headers = {
        "Authorization": f"Bearer {se.civitai.api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Civitai image request: dims=%dx%d loras=%s",
        width,
        height,
        [lo.get("model", "") for lo in loras] if loras else None,
    )

    async with _get_civitai_semaphore():
        try:
            async with asyncio.timeout(se.civitai.total_timeout):
                session = get_http_session()
                async with session.post(
                    CIVITAI_WORKFLOW_URL,
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status not in (200, 202):
                        error_text = await response.text()
                        raise ImageGenerationError(
                            f"Ошибка Civitai ({response.status}): {error_text[:300]}"
                        )

                    if response.status == 200:
                        body_bytes = await response.read()
                        if len(body_bytes) > 1000:
                            return body_bytes

                    payload = await response.json(content_type=None)

                workflow_id = payload.get("id", "")
                logger.info(
                    "Civitai workflow %s submitted, status=%s",
                    workflow_id[-16:],
                    payload.get("status"),
                )
                if on_submit is not None and workflow_id:
                    await on_submit(workflow_id)

                image_bytes = await _poll_civitai_image(
                    session=session,
                    workflow_id=workflow_id,
                    auth_key=se.civitai.api_key,
                )
                if image_bytes is not None:
                    return image_bytes

                raise ImageGenerationError(
                    f"Civitai: не удалось получить изображение из воркфлоу {workflow_id or 'unknown'}"
                )
        except TimeoutError as exc:
            raise ImageGenerationTimeoutError(
                f"Превышено время ожидания Civitai (total_timeout={se.civitai.total_timeout}s)."
            ) from exc


async def poll_civitai_workflow(workflow_id: str, auth_key: str | None = None) -> bytes:
    """Доопросить уже отправленный воркфлоу CivitAI и вернуть изображение.

    Используется воркером для возобновления генерации после рестарта бота:
    воркфлоу живёт на стороне CivitAI, поэтому по сохранённому ``workflow_id``
    результат можно забрать без повторной отправки и повторного списания.
    """
    key = auth_key or se.civitai.api_key
    if not key:
        raise ImageGenerationError("Не настроен ключ Civitai (CIVITAI_API_KEY).")
    if not workflow_id:
        raise ImageGenerationError("Civitai: пустой workflow_id для доопроса.")

    async with _get_civitai_semaphore():
        try:
            async with asyncio.timeout(se.civitai.total_timeout):
                session = get_http_session()
                image_bytes = await _poll_civitai_image(
                    session=session,
                    workflow_id=workflow_id,
                    auth_key=key,
                )
        except TimeoutError as exc:
            raise ImageGenerationTimeoutError(
                f"Превышено время ожидания Civitai (total_timeout={se.civitai.total_timeout}s)."
            ) from exc

    if image_bytes is None:
        raise ImageGenerationError(
            f"Civitai: не удалось получить изображение из воркфлоу {workflow_id or 'unknown'}"
        )
    return image_bytes


async def _poll_civitai_image(
    session: aiohttp.ClientSession,
    workflow_id: str,
    auth_key: str,
) -> bytes | None:
    workflow_url = f"{CIVITAI_WORKFLOW_URL}/{workflow_id}"
    headers = {
        "Authorization": f"Bearer {auth_key}",
        "Accept": "application/json",
    }

    poll_timeout = aiohttp.ClientTimeout(total=15)

    # Число опросов выводим из настроенного total_timeout (+2 с запасом), иначе
    # фиксированный range(N) сам обрезал бы ожидание раньше внешнего asyncio.timeout.
    max_attempts = int(se.civitai.total_timeout / CIVITAI_POLL_INTERVAL) + 2
    for attempt in range(max_attempts):
        await asyncio.sleep(CIVITAI_POLL_INTERVAL)

        try:
            async with session.get(
                workflow_url, headers=headers, timeout=poll_timeout
            ) as resp:
                if resp.status != 200:
                    logger.warning("Civitai poll %d: HTTP %d", attempt + 1, resp.status)
                    continue

                payload = await resp.json(content_type=None)
                status = payload.get("status", "")
                wf_id_short = workflow_id[-12:]

                if status == "failed":
                    reason = (
                        payload.get("failureReason")
                        or payload.get("reason")
                        or "unknown"
                    )
                    raise ImageGenerationError(
                        f"Civitai воркфлоу {wf_id_short} завершился ошибкой: {reason}"
                    )

                if status != "succeeded":
                    if attempt == 0:
                        logger.info(
                            "Civitai workflow %s: %s, waiting...", wf_id_short, status
                        )
                    continue

                for step in payload.get("steps", []):
                    for img in step.get("output", {}).get("images", []):
                        available = img.get("available", False)
                        image_url = img.get("url") or img.get("previewUrl")
                        if image_url and available:
                            data = await _download_blob(image_url, auth_key)
                            if data is not None:
                                logger.info(
                                    "Civitai workflow %s done, image %dx%d",
                                    wf_id_short,
                                    img.get("width"),
                                    img.get("height"),
                                )
                                return data
                            logger.warning(
                                "Civitai blob download returned empty, retrying..."
                            )
                            continue
                        if image_url and not available:
                            logger.info("Civitai image not available yet, retrying...")
                            continue

                logger.info(
                    "Civitai workflow %s succeeded but no ready image, retrying...",
                    wf_id_short,
                )

        except ImageGenerationError:
            raise
        except Exception:
            logger.exception("Civitai poll %d exception", attempt + 1)

    logger.error(
        "Civitai polling exhausted after 50 attempts for %s", workflow_id[-12:]
    )
    return None
