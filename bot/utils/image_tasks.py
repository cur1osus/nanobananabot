from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


async def enqueue_fake_image_task(*, model_key: str, prompt: str, photo_ids: list[str]) -> str:
    """
    Fake enqueue placeholder for image generation tasks.

    TODO: Replace with real image backend API integration.
    """
    task_id = uuid.uuid4().hex[:10]
    logger.info(
        "TODO: enqueue image generation task. model=%s photos=%s prompt_len=%s task_id=%s",
        model_key,
        len(photo_ids),
        len(prompt),
        task_id,
    )
    return task_id
