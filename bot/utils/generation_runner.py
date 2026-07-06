from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile
from sqlalchemy import select

from bot.db.enum import GenerationKind, GenerationTaskStatus
from bot.db.models import GenerationTaskModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.inline import ik_back_home, ik_image_result_actions
from bot.utils.admin_notify import notify_admins_error
from bot.utils.billing import refund_generation
from bot.utils.http import get_http_session
from bot.utils.image_models import (
    PRODIA_FALLBACK_MODEL_KEY,
    get_image_model,
    is_adult_model_key,
)
from bot.utils.image_tasks import (
    ImageGenerationError,
    ImageGenerationTimeoutError,
    ImageModerationError,
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

# Максимум повторов первичной доставки при флуд-контроле Telegram.
_DELIVERY_RETRY_ATTEMPTS = 3


@dataclass
class _ImageDelivery:
    chat_id: int
    image_bytes: bytes
    doc_filename: str
    caption: str
    is_create: bool


@dataclass
class _VideoDelivery:
    chat_id: int
    video_bytes: bytes
    filename: str
    caption: str


async def run_generation_task(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    task_id: int,
) -> None:
    """Выполнить одну генерацию из очереди и доставить результат.

    Задача уже переведена диспетчером в ``processing``. Порядок гарантий:

    1. Пока результат не получен — любая ошибка возвращает кредиты и помечает
       задачу ``refunded``.
    2. Как только результат сгенерирован, доставляем его пользователю. Если
       **первичная** отправка (превью-фото / видео) не удалась — пользователь
       ничего не увидел, поэтому кредиты возвращаются как при ошибке генерации.
    3. Как только первичная отправка прошла, задача считается ``success`` и
       кредиты остаются списанными. Оставшиеся отправки (файл без сжатия) —
       best-effort: их сбой логируется, но НЕ приводит к возврату (иначе
       пользователь получил бы результат бесплатно).
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
                delivery: _ImageDelivery | _VideoDelivery | None = await _run_video(
                    bot=bot, task=task, params=params
                )
            else:
                delivery = await _run_image(
                    bot=bot, session=session, task=task, params=params
                )
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

        if delivery is None:
            # Нечего доставлять (нет chat_id) — результат получен, кредиты
            # остаются списанными.
            task.status = GenerationTaskStatus.SUCCESS.value
            await session.commit()
            return

        # Первичная доставка: её успех == «пользователь получил результат».
        try:
            await _deliver_primary(bot, delivery)
        except Exception as exc:
            await _fail(
                bot=bot,
                session=session,
                redis=redis,
                user=user,
                task=task,
                params=params,
                error=exc,
                text="❌ Не удалось доставить результат. Кредиты возвращены, "
                "попробуйте ещё раз чуть позже.",
            )
            return

        # Точка невозврата: результат доставлен, кредиты остаются списанными.
        task.status = GenerationTaskStatus.SUCCESS.value
        await session.commit()

        # Остаток доставки (файл без сжатия) — best-effort, без возврата.
        try:
            await _deliver_rest(bot, delivery)
        except Exception:
            logger.warning(
                "Дополнительная доставка задачи %s не удалась (без возврата)",
                task.id,
                exc_info=True,
            )

        await _delete_status_message(bot, task)


async def _run_image(
    *,
    bot: Bot,
    session: AsyncSession,
    task: GenerationTaskModel,
    params: dict[str, Any],
) -> _ImageDelivery | None:
    model_key = str(params.get("model_key", ""))
    model = get_image_model(model_key)
    prompt = str(params.get("prompt", ""))
    aspect_ratio = str(params.get("aspect_ratio", "auto"))
    photos = [str(p) for p in params.get("photos", [])]
    is_create = task.kind == GenerationKind.IMAGE_CREATE.value
    scenario_strength = params.get("strength")
    scenario_steps = params.get("steps")

    positive_prompt = f"{model.prompt_prefix}{prompt}".strip()
    used_fallback = False

    # CivitAI: при наличии сохранённого workflow_id доопрашиваем уже отправленную
    # генерацию вместо повторной отправки (переживание рестарта).
    if model.provider == "civitai" and task.provider_task_id:
        from bot.utils.civitai_api import poll_civitai_workflow

        image_bytes = await poll_civitai_workflow(task.provider_task_id)
    else:
        reference_images = (
            await _fetch_reference_images(bot, photos) if not is_create else None
        )
        # Редактирование без единого пригодного референса превратилось бы в
        # text-to-image по одному промпту — это не то, за что заплатил
        # пользователь. Считаем это ошибкой генерации (кредиты вернутся).
        if not is_create and photos and not reference_images:
            raise ImageGenerationError(
                "Не удалось подготовить ни одного референс-изображения."
            )

        async def _persist_workflow_id(workflow_id: str) -> None:
            task.provider_task_id = workflow_id
            await session.commit()

        is_4k = bool(params.get("is_4k", False))

        try:
            image_bytes = await generate_image(
                prompt=positive_prompt,
                model=model.create_api_model if is_create else model.api_model,
                provider=model.provider,
                reference_images=reference_images,
                aspect_ratio=aspect_ratio,
                output_format="jpeg",
                negative_prompt=model.negative_prompt or None,
                img2img_mode=model.img2img_mode,
                steps=scenario_steps if scenario_steps is not None else model.steps,
                cfg_scale=model.cfg_scale,
                loras=list(model.loras) if model.loras else None,
                strength=scenario_strength,
                on_civitai_submit=_persist_workflow_id,
                is_4k=is_4k,
            )
        except ImageModerationError:
            # Раздел 18+ уже на open-weights модели — фолбэку неоткуда взяться.
            if is_adult_model_key(model_key):
                raise
            # Основная модель отклонила запрос по модерации — повторяем через
            # запасную open-weights модель (Prodia, без модерации).
            fallback = get_image_model(PRODIA_FALLBACK_MODEL_KEY)
            logger.info(
                "Модерация модели %s, фолбэк на %s (Prodia)",
                model_key,
                fallback.key,
            )
            image_bytes = await generate_image(
                prompt=prompt,
                model=fallback.create_api_model if is_create else fallback.api_model,
                provider=fallback.provider,
                reference_images=reference_images,
                aspect_ratio=aspect_ratio,
                output_format="jpeg",
            )
            used_fallback = True

    chat_id = task.chat_id
    if chat_id is None:
        return None

    if used_fallback:
        notice = (
            "⚠️ Основная модель отклонила запрос (модерация). "
            "Сгенерировано запасной моделью без модерации.\n\n"
        )
        model_line = ""
    else:
        notice = ""
        model_line = (
            "" if is_adult_model_key(model_key) else f"🎨 Модель: {model.title}\n"
        )

    caption = (
        f"{notice}✅ Готово!\n{model_line}💰 Списано: {task.credits_cost} кредитов"
    )
    return _ImageDelivery(
        chat_id=chat_id,
        image_bytes=image_bytes,
        doc_filename=f"generation_{task.id}_{model_key}.jpg",
        caption=caption,
        is_create=is_create,
    )


async def _run_video(
    *,
    bot: Bot,
    task: GenerationTaskModel,
    params: dict[str, Any],
) -> _VideoDelivery | None:
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
        return None

    caption = (
        f"🎬 Готово!\n"
        f"📹 Модель: {model.title}\n"
        f"⏱ Длительность: {duration} сек.\n"
        f"💰 Списано: {task.credits_cost} кредитов"
    )
    return _VideoDelivery(
        chat_id=chat_id,
        video_bytes=video_bytes,
        filename=f"video_{task.id}.mp4",
        caption=caption,
    )


async def _send_with_retry(factory: Any) -> None:
    """Отправить, повторяя при флуд-контроле Telegram (TelegramRetryAfter)."""
    for attempt in range(_DELIVERY_RETRY_ATTEMPTS):
        try:
            await factory()
            return
        except TelegramRetryAfter as err:
            if attempt == _DELIVERY_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(err.retry_after)


async def _deliver_primary(bot: Bot, delivery: _ImageDelivery | _VideoDelivery) -> None:
    if isinstance(delivery, _ImageDelivery):
        markup = (
            await ik_back_home()
            if delivery.is_create
            else await ik_image_result_actions()
        )
        await _send_with_retry(
            lambda: bot.send_photo(
                delivery.chat_id,
                photo=BufferedInputFile(
                    file=delivery.image_bytes, filename="preview.jpg"
                ),
                caption=delivery.caption,
                reply_markup=markup,
            )
        )
        return

    await _send_with_retry(
        lambda: bot.send_video(
            delivery.chat_id,
            video=BufferedInputFile(
                file=delivery.video_bytes, filename=delivery.filename
            ),
            caption=delivery.caption,
            reply_markup=None,
        )
    )


async def _deliver_rest(bot: Bot, delivery: _ImageDelivery | _VideoDelivery) -> None:
    if isinstance(delivery, _ImageDelivery):
        await bot.send_document(
            delivery.chat_id,
            document=BufferedInputFile(
                file=delivery.image_bytes, filename=delivery.doc_filename
            ),
            caption="📎 Файл результата",
        )
        return

    await bot.send_document(
        delivery.chat_id,
        document=BufferedInputFile(
            file=delivery.video_bytes, filename=delivery.filename
        ),
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
