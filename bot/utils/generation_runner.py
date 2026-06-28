from __future__ import annotations

import base64
import json
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import select

from bot.db.enum import GenerationKind, GenerationTaskStatus
from bot.db.models import GenerationTaskModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.inline import ik_back_home, ik_image_result_actions
from bot.utils.admin_notify import notify_admins_error
from bot.utils.billing import refund_generation
from bot.utils.http import get_http_session
from bot.utils.image_models import get_image_model, is_adult_model_key
from bot.utils.image_tasks import (
    ImageGenerationError,
    ImageGenerationTimeoutError,
    generate_image,
    image_generation_error_text,
)
from bot.utils.video_models import get_kling_model
from bot.utils.video_tasks import (
    VideoGenerationError,
    VideoGenerationTimeoutError,
    generate_video,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


async def run_generation_task(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    task_id: int,
) -> None:
    """Выполнить одну генерацию из очереди и доставить результат.

    Задача уже переведена диспетчером в ``processing``. На любой ошибке кредиты
    возвращаются, задача помечается ``refunded``, пользователю отправляется
    понятное сообщение.
    """
    async with sessionmaker() as session:
        task = await session.get(GenerationTaskModel, task_id)
        if task is None or task.status != GenerationTaskStatus.PROCESSING.value:
            return

        user_db = await session.scalar(
            select(UserModel).where(UserModel.id == task.user_idpk)
        )
        if user_db is None:
            task.status = GenerationTaskStatus.ERROR.value
            await session.commit()
            logger.warning("Генерация %s: пользователь не найден", task_id)
            return
        user = UserRD.from_orm(user_db)

        params: dict[str, Any] = json.loads(task.params or "{}")
        try:
            if task.kind == GenerationKind.VIDEO.value:
                await _run_video(bot=bot, task=task, params=params)
            else:
                await _run_image(bot=bot, session=session, task=task, params=params)
        except (
            ImageGenerationError,
            ImageGenerationTimeoutError,
            VideoGenerationError,
            VideoGenerationTimeoutError,
        ) as exc:
            await _fail(
                bot=bot,
                session=session,
                redis=redis,
                user=user,
                task=task,
                params=params,
                error=exc,
                text=_error_text(task.kind, exc),
            )
            return
        except Exception as exc:  # любая ошибка должна вернуть кредиты
            await _fail(
                bot=bot,
                session=session,
                redis=redis,
                user=user,
                task=task,
                params=params,
                error=exc,
                text=_error_text(task.kind, exc),
            )
            return

        task.status = GenerationTaskStatus.SUCCESS.value
        await session.commit()
        await _delete_status_message(bot, task)


async def _run_image(
    *,
    bot: Bot,
    session: AsyncSession,
    task: GenerationTaskModel,
    params: dict[str, Any],
) -> None:
    model_key = str(params.get("model_key", ""))
    model = get_image_model(model_key)
    prompt = str(params.get("prompt", ""))
    aspect_ratio = str(params.get("aspect_ratio", "auto"))
    photos = [str(p) for p in params.get("photos", [])]
    is_create = task.kind == GenerationKind.IMAGE_CREATE.value

    positive_prompt = f"{model.prompt_prefix}{prompt}".strip()

    # CivitAI: при наличии сохранённого workflow_id доопрашиваем уже отправленную
    # генерацию вместо повторной отправки (переживание рестарта).
    if model.provider == "civitai" and task.provider_task_id:
        from bot.utils.civitai_api import poll_civitai_workflow

        image_bytes = await poll_civitai_workflow(task.provider_task_id)
    else:
        reference_images = (
            await _fetch_reference_images(bot, photos) if not is_create else None
        )

        async def _persist_workflow_id(workflow_id: str) -> None:
            task.provider_task_id = workflow_id
            await session.commit()

        image_bytes = await generate_image(
            prompt=positive_prompt,
            model=model.create_api_model if is_create else model.api_model,
            provider=model.provider,
            reference_images=reference_images,
            aspect_ratio=aspect_ratio,
            output_format="jpeg",
            negative_prompt=model.negative_prompt or None,
            img2img_mode=model.img2img_mode,
            steps=model.steps,
            cfg_scale=model.cfg_scale,
            loras=list(model.loras) if model.loras else None,
            on_civitai_submit=_persist_workflow_id,
        )

    chat_id = task.chat_id
    if chat_id is None:
        return

    filename = f"generation_{task.id}_{model_key}.jpg"
    await bot.send_document(
        chat_id,
        document=BufferedInputFile(file=image_bytes, filename=filename),
        caption="📎 Файл результата",
    )
    model_line = "" if is_adult_model_key(model_key) else f"🎨 Модель: {model.title}\n"
    await bot.send_photo(
        chat_id,
        photo=BufferedInputFile(file=image_bytes, filename="preview.jpg"),
        caption=f"✅ Готово!\n{model_line}💰 Списано: {task.credits_cost} кредитов",
        reply_markup=(
            await ik_back_home() if is_create else await ik_image_result_actions()
        ),
    )


async def _run_video(
    *,
    bot: Bot,
    task: GenerationTaskModel,
    params: dict[str, Any],
) -> None:
    model_key = str(params.get("model_key", ""))
    model = get_kling_model(model_key)
    prompt = str(params.get("prompt", "")).strip()
    aspect_ratio = str(params.get("aspect_ratio", "1:1"))
    duration = int(params.get("duration", 5))
    with_audio = bool(params.get("with_audio", True))
    image_file_id = params.get("image_file_id") or ""

    reference_image = (
        await _fetch_video_reference(bot, str(image_file_id)) if image_file_id else None
    )

    video_bytes = await generate_video(
        prompt=prompt,
        runware_model=model.runware_model,
        duration=duration,
        aspect_ratio=aspect_ratio,
        with_audio=with_audio,
        reference_image=reference_image,
        supports_duration=model.supports_duration,
        supports_dimensions=model.supports_dimensions,
        supports_sound=model.supports_sound,
        ratio_dims=model.ratio_dims,
        needs_provider_settings=model.needs_provider_settings,
    )

    chat_id = task.chat_id
    if chat_id is None:
        return

    filename = f"video_{task.id}.mp4"
    await bot.send_video(
        chat_id,
        video=BufferedInputFile(file=video_bytes, filename=filename),
        caption=(
            f"🎬 Готово!\n"
            f"📹 Модель: {model.title}\n"
            f"⏱ Длительность: {duration} сек.\n"
            f"💰 Списано: {task.credits_cost} кредитов"
        ),
        reply_markup=await ik_back_home(),
    )
    await bot.send_document(
        chat_id,
        document=BufferedInputFile(file=video_bytes, filename=filename),
        caption="📥 Без сжатия",
    )


async def _fail(
    *,
    bot: Bot,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    task: GenerationTaskModel,
    params: dict[str, Any],
    error: Exception,
    text: str,
) -> None:
    logger.exception("Ошибка генерации %s", task.id, exc_info=error)
    await refund_generation(
        session=session,
        redis=redis,
        user=user,
        task=task,
        cost=task.credits_cost,
    )
    await _edit_status_message(bot, task, text)

    title = (
        "Ошибка генерации видео"
        if task.kind == GenerationKind.VIDEO.value
        else "Ошибка генерации изображения"
    )
    await notify_admins_error(
        bot,
        title,
        error,
        context={
            "user_id": user.user_id,
            "kind": task.kind,
            "model": params.get("model_key"),
            "prompt": str(params.get("prompt", ""))[:200],
        },
    )


def _error_text(kind: str, error: Exception) -> str:
    if kind == GenerationKind.VIDEO.value:
        if isinstance(error, VideoGenerationTimeoutError):
            return (
                "❌ Генерация видео заняла слишком много времени.\n\n"
                "Попробуйте ещё раз чуть позже."
            )
        return "❌ Не удалось сгенерировать видео.\n\nПопробуйте ещё раз чуть позже."
    return image_generation_error_text(error)


async def _fetch_reference_images(bot: Bot, photo_ids: list[str]) -> list[bytes]:
    bot_token = getattr(bot, "token", "")
    if not bot_token:
        return []
    images: list[bytes] = []
    for file_id in photo_ids[:10]:
        try:
            file = await bot.get_file(file_id)
            if not file.file_path:
                continue
            images.append(await _download_telegram_file(bot_token, file.file_path))
        except Exception:
            logger.exception("Не удалось подготовить референс: file_id=%s", file_id)
    return images


async def _fetch_video_reference(bot: Bot, file_id: str) -> str | None:
    bot_token = getattr(bot, "token", "")
    if not bot_token:
        return None
    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        img_bytes = await _download_telegram_file(bot_token, file.file_path)
    except Exception:
        logger.exception("Не удалось подготовить референс видео: file_id=%s", file_id)
        return None
    return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode("ascii")


async def _download_telegram_file(bot_token: str, file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    timeout = aiohttp.ClientTimeout(total=60)
    session = get_http_session()
    async with session.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return await response.read()


async def _delete_status_message(bot: Bot, task: GenerationTaskModel) -> None:
    if task.chat_id is None or task.status_message_id is None:
        return
    try:
        await bot.delete_message(task.chat_id, task.status_message_id)
    except Exception:
        logger.debug("Не удалось удалить статус-сообщение задачи %s", task.id)


async def _edit_status_message(bot: Bot, task: GenerationTaskModel, text: str) -> None:
    if task.chat_id is None or task.status_message_id is None:
        return
    try:
        await bot.edit_message_text(
            text, chat_id=task.chat_id, message_id=task.status_message_id
        )
    except Exception:
        logger.debug("Не удалось обновить статус-сообщение задачи %s", task.id)
