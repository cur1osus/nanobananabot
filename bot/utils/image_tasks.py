from __future__ import annotations

import base64
import logging
import uuid

import aiohttp

from bot.settings import se

logger = logging.getLogger(__name__)


async def generate_image(
    prompt: str,
    photo_ids: list[str] | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> bytes:
    """Generate image using VseGPT API.

    Uses /images/generations endpoint for image generation.
    For img-google/nano-banana-2 model:
    - response_format: "b64_json" (required)
    - output_format: "jpeg" | "png" (default: "jpeg")
    - aspect_ratio: "1:1", "16:9", etc.
    """
    headers = {
        "Authorization": f"Bearer {se.image_backend.api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": se.image_backend.model,
        "prompt": prompt,
        "response_format": "b64_json",
        "aspect_ratio": aspect_ratio,
        "output_format": output_format,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{se.image_backend.base_url}/images/generations",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=se.image_backend.timeout),
        ) as response:
            response.raise_for_status()
            data = await response.json()

            # Extract base64 image from response
            # VseGPT returns: {"data": [{"b64_json": "..."}]}
            if "data" in data and len(data["data"]) > 0:
                b64_image = data["data"][0].get("b64_json", "")
                if b64_image:
                    return base64.b64decode(b64_image)

            raise RuntimeError(f"No image in API response: {data}")


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
