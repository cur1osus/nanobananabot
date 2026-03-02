from __future__ import annotations

import base64
import logging
import uuid
from io import BytesIO

import aiohttp

from bot.settings import se

logger = logging.getLogger(__name__)


async def enqueue_fake_image_task(
    *,
    model_key: str,
    prompt: str,
    photo_ids: list[str],
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> str:
    """Generate image using VseGPT API (OpenAI compatible).

    For img-google/nano-banana-2 model:
    - response_format: "b64_json" (required)
    - output_format: "jpeg" | "png" (default: "jpeg")
    - aspect_ratio: "1:1", "16:9", etc.
    """
    task_id = uuid.uuid4().hex[:10]

    headers = {
        "Authorization": f"Bearer {se.image_backend.api_key}",
        "Content-Type": "application/json",
    }

    # Build messages with images if provided
    messages = []
    content = []

    # Add text prompt
    content.append({"type": "text", "text": prompt})

    # TODO: Download and encode photos to base64 if photo_ids provided
    # For now, we'll send just the text prompt

    messages.append(
        {"role": "user", "content": content if len(content) > 1 else prompt}
    )

    payload = {
        "model": se.image_backend.model,
        "messages": messages,
        "response_format": "b64_json",
        "extra_body": {
            "output_format": output_format,
            "aspect_ratio": aspect_ratio,
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{se.image_backend.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=se.image_backend.timeout),
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(
                        "Image generation failed: status=%s response=%s",
                        response.status,
                        text,
                    )
                    raise RuntimeError(f"API error: {response.status}")

                data = await response.json()

                # Extract base64 image from response
                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0].get("message", {})
                    content_data = message.get("content", "")

                    # Parse JSON content if it's a string
                    if isinstance(content_data, str):
                        import json

                        try:
                            content_json = json.loads(content_data)
                            b64_image = content_json.get("image", "")
                        except json.JSONDecodeError:
                            b64_image = content_data
                    else:
                        b64_image = content_data.get("image", "")

                    if b64_image:
                        # Save image or return it
                        logger.info(
                            "Image generated successfully: task_id=%s model=%s",
                            task_id,
                            model_key,
                        )
                        # TODO: Save image to file/storage and return URL/path
                        return task_id

                logger.error("Unexpected API response structure: %s", data)
                raise RuntimeError("Invalid API response")

    except Exception as e:
        logger.error("Image generation error: %s", e, exc_info=True)
        raise

    return task_id


async def generate_image(
    prompt: str,
    photo_ids: list[str] | None = None,
    aspect_ratio: str = "1:1",
    output_format: str = "jpeg",
) -> bytes:
    """Generate image and return image bytes."""
    headers = {
        "Authorization": f"Bearer {se.image_backend.api_key}",
        "Content-Type": "application/json",
    }

    messages = [{"role": "user", "content": prompt}]

    payload = {
        "model": se.image_backend.model,
        "messages": messages,
        "response_format": "b64_json",
        "extra_body": {
            "output_format": output_format,
            "aspect_ratio": aspect_ratio,
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{se.image_backend.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=se.image_backend.timeout),
        ) as response:
            response.raise_for_status()
            data = await response.json()

            # Extract and decode base64 image
            if "choices" in data and len(data["choices"]) > 0:
                message = data["choices"][0].get("message", {})
                content_data = message.get("content", "")

                # Parse JSON content if it's a string
                if isinstance(content_data, str):
                    import json

                    try:
                        content_json = json.loads(content_data)
                        b64_image = content_json.get("image", "")
                    except json.JSONDecodeError:
                        b64_image = content_data
                else:
                    b64_image = content_data.get("image", "")

                if b64_image:
                    return base64.b64decode(b64_image)

            raise RuntimeError("No image in API response")
