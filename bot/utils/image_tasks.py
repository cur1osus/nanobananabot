from __future__ import annotations

import asyncio
import base64
import logging

import aiohttp
from runware import IImageInference, Runware

from bot.settings import se

logger = logging.getLogger(__name__)

ASPECT_RATIO_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "3:2": (1264, 848),
    "2:3": (848, 1264),
    "4:3": (1200, 896),
    "3:4": (896, 1200),
    "5:4": (1152, 928),
    "4:5": (928, 1152),
    "16:9": (1376, 768),
    "9:16": (768, 1376),
    "21:9": (1536, 672),
    "auto": (1024, 1024),
}

# google:4@1 (Nano Banana 1) supports only these exact pixel dimensions
_NANO_BANANA_1_DIMS: dict[str, tuple[int, int]] = {
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

_WAN_27_IMAGE_DIMS: dict[str, tuple[int, int]] = {
    **ASPECT_RATIO_DIMS,
    "21:9": (1792, 768),
}

_MODEL_DIMS: dict[str, dict[str, tuple[int, int]]] = {
    "google:4@1": _NANO_BANANA_1_DIMS,
    "alibaba:wan@2.7-image": _WAN_27_IMAGE_DIMS,
}

# These Runware model docs require reference images under inputs.referenceImages.
_INPUT_REFERENCE_IMAGE_MODELS: set[str] = {
    "alibaba:wan@2.7-image",
    "bfl:7@1",
    "openai:gpt-image@2",
    "runware:400@1",
    "runware:400@2",
}

_OUTPUT_FORMAT_MAP: dict[str, str] = {
    "jpeg": "JPG",
    "jpg": "JPG",
    "png": "PNG",
    "webp": "WEBP",
}

# Сила преобразования для классического img2img (seedImage): чем выше, тем сильнее
# результат отходит от исходного фото. 0.3 — лёгкая правка с сохранением исходной композиции.
DEFAULT_IMG2IMG_STRENGTH: float = 0.3

# Повтор при failedModelLoad (on-demand загрузка CivitAI-модели): базовая пауза растёт
# линейно. Число попыток ограничено отдельно, чтобы суммарные паузы укладывались в
# IMAGE_BACKEND_TOTAL_TIMEOUT (по умолчанию 150с).
_MODEL_LOAD_RETRY_DELAY: float = 12.0
_MODEL_LOAD_MAX_ATTEMPTS: int = 3

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


def _aspect_ratio_to_dims(aspect_ratio: str, model_id: str | None = None) -> tuple[int, int]:
    dims = _MODEL_DIMS.get(model_id or "", ASPECT_RATIO_DIMS) if model_id else ASPECT_RATIO_DIMS
    return dims.get(aspect_ratio, dims["1:1"])


def closest_aspect_ratio(width: int, height: int) -> str:
    if height == 0:
        return "1:1"
    target = width / height
    candidates = {k: v for k, v in ASPECT_RATIO_DIMS.items() if k != "auto"}
    return min(candidates, key=lambda k: abs(candidates[k][0] / candidates[k][1] - target))


def _build_image_inference_request(
    *,
    model_id: str,
    prompt: str,
    width: int,
    height: int,
    output_format: str,
    reference_images: list[str] | None,
    negative_prompt: str | None = None,
    img2img_mode: str = "reference",
    strength: float = DEFAULT_IMG2IMG_STRENGTH,
    steps: int | None = None,
    cfg_scale: float | None = None,
) -> IImageInference:
    refs = reference_images or []
    request_kwargs = {
        "model": model_id,
        "positivePrompt": prompt,
        "width": width,
        "height": height,
        "outputType": "URL",
        "outputFormat": output_format,
        "numberResults": 1,
    }

    if negative_prompt:
        request_kwargs["negativePrompt"] = negative_prompt
    if steps is not None:
        request_kwargs["steps"] = steps
    if cfg_scale is not None:
        request_kwargs["CFGScale"] = cfg_scale

    if refs:
        if img2img_mode == "seed":
            # Классический SDXL/Pony img2img: одно исходное фото + сила преобразования.
            request_kwargs["seedImage"] = refs[0]
            request_kwargs["strength"] = strength
        elif model_id in _INPUT_REFERENCE_IMAGE_MODELS:
            request_kwargs["inputs"] = {"referenceImages": refs}
        else:
            request_kwargs["referenceImages"] = refs

    return IImageInference(**request_kwargs)


async def _download_image(url: str, *, timeout: int) -> bytes:
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=request_timeout) as response:
            if response.status >= 400:
                raise ImageGenerationError(
                    f"Не удалось скачать изображение Runware ({response.status})"
                )
            return await response.read()


def _bytes_to_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


async def generate_image(
    prompt: str,
    photo_ids: list[str] | None = None,
    model: str | None = None,
    provider: str = "runware",
    reference_images: list[bytes] | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
    negative_prompt: str | None = None,
    img2img_mode: str = "reference",
    steps: int | None = None,
    cfg_scale: float | None = None,
) -> bytes:
    """Generate image via Runware.

    ``reference_images`` are raw image bytes, encoded as base64 data URLs.
    """
    del photo_ids, provider

    if se.image_backend.provider != "runware":
        raise ImageGenerationError(
            "Поддерживается только IMAGE_BACKEND_PROVIDER=runware."
        )
    if not se.image_backend.api_key:
        raise ImageGenerationError(
            "Не настроен ключ API для генерации изображений (IMAGE_BACKEND_API_KEY)."
        )

    model_id = model or se.image_backend.model
    width, height = _aspect_ratio_to_dims(aspect_ratio, model_id)
    fmt = _OUTPUT_FORMAT_MAP.get(output_format.lower(), "JPG")
    data_url_refs = (
        [_bytes_to_data_url(image) for image in reference_images]
        if reference_images
        else None
    )

    logger.info(
        "Image generation request: provider=runware model=%s refs=%s dims=%dx%d",
        model_id,
        len(reference_images or []),
        width,
        height,
    )

    request = _build_image_inference_request(
        model_id=model_id,
        prompt=prompt,
        width=width,
        height=height,
        output_format=fmt,
        reference_images=data_url_refs,
        negative_prompt=negative_prompt,
        img2img_mode=img2img_mode,
        steps=steps,
        cfg_scale=cfg_scale,
    )

    async with _get_runware_semaphore():
        try:
            async with asyncio.timeout(se.image_backend.total_timeout):
                client = await _get_runware_client()
                # CivitAI-чекпойнты грузятся on-demand: первый запрос может вернуть
                # failedModelLoad, пока модель подгружается. Повторяем с паузой.
                max_attempts = _MODEL_LOAD_MAX_ATTEMPTS
                images = None
                for attempt in range(max_attempts):
                    try:
                        images = await client.imageInference(requestImage=request)
                        break
                    except Exception as exc:
                        if "failedModelLoad" in str(exc) and attempt + 1 < max_attempts:
                            delay = _MODEL_LOAD_RETRY_DELAY * (attempt + 1)
                            logger.warning(
                                "Runware failedModelLoad (model=%s), retry in %.0fs "
                                "(attempt %d/%d)",
                                model_id, delay, attempt + 1, max_attempts,
                            )
                            await asyncio.sleep(delay)
                            continue
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
