from __future__ import annotations

import base64
import logging
import uuid

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.func import deduct_user_credits
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import VideoNav, VideoSetting
from bot.keyboards.inline import (
    ik_back_home,
    ik_video_back_to_settings,
    ik_video_settings,
)
from bot.states import VideoGenerationState
from bot.utils.admin_notify import notify_admins_error
from bot.utils.messaging import edit_or_answer
from bot.utils.video_models import get_kling_model, video_cost
from bot.utils.video_state import get_video_data, update_video_data, video_settings_text
from bot.utils.video_tasks import (
    VideoGenerationError,
    VideoGenerationTimeoutError,
    generate_video,
)

router = Router()
logger = logging.getLogger(__name__)


async def _open_settings(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await get_video_data(state)
    await state.set_state(VideoGenerationState.settings)
    await edit_or_answer(
        query,
        text=video_settings_text(data),
        reply_markup=await ik_video_settings(
            model_key=data.model_key,
            duration=data.duration,
            aspect_ratio=data.aspect_ratio,
            with_audio=data.with_audio,
        ),
    )


@router.callback_query(VideoSetting.filter())
async def handle_video_setting(
    query: CallbackQuery,
    callback_data: VideoSetting,
    state: FSMContext,
) -> None:
    await query.answer()
    data = await get_video_data(state)

    if callback_data.setting == "model":
        from bot.utils.video_models import is_kling_model_key
        if is_kling_model_key(callback_data.value):
            data.model_key = callback_data.value

    elif callback_data.setting == "duration":
        try:
            d = int(callback_data.value)
            if d in (5, 10):
                data.duration = d
        except ValueError:
            pass

    elif callback_data.setting == "ratio":
        from bot.utils.video_models import VIDEO_RATIOS
        ratio = callback_data.value.replace("x", ":")
        if ratio in VIDEO_RATIOS:
            data.aspect_ratio = ratio

    elif callback_data.setting == "audio":
        data.with_audio = callback_data.value == "1"

    from bot.utils.video_state import set_video_data
    await set_video_data(state, data)
    await state.set_state(VideoGenerationState.settings)

    await edit_or_answer(
        query,
        text=video_settings_text(data),
        reply_markup=await ik_video_settings(
            model_key=data.model_key,
            duration=data.duration,
            aspect_ratio=data.aspect_ratio,
            with_audio=data.with_audio,
        ),
    )


@router.callback_query(VideoNav.filter(F.action == "set_prompt"))
async def ask_video_prompt(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    await query.answer()
    await state.set_state(VideoGenerationState.waiting_prompt)
    await edit_or_answer(
        query,
        text="📝 Опишите видео, которое хотите сгенерировать.\n\nНапример: «Кот прыгает на стол в стиле slow motion».",
        reply_markup=await ik_video_back_to_settings(),
    )


@router.message(VideoGenerationState.waiting_prompt, F.text)
async def collect_video_prompt(
    message: Message,
    state: FSMContext,
) -> None:
    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Пожалуйста, введите текстовое описание видео.")
        return

    data = await update_video_data(state, prompt=prompt)
    await state.set_state(VideoGenerationState.settings)
    await message.answer(
        video_settings_text(data),
        reply_markup=await ik_video_settings(
            model_key=data.model_key,
            duration=data.duration,
            aspect_ratio=data.aspect_ratio,
            with_audio=data.with_audio,
        ),
    )


@router.callback_query(VideoNav.filter(F.action == "set_image"))
async def ask_video_image(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    await query.answer()
    await state.set_state(VideoGenerationState.waiting_image)
    await edit_or_answer(
        query,
        text="🖼 Пришлите изображение, которое станет основой для видео.\n\nИли нажмите «← К настройкам», чтобы продолжить без изображения.",
        reply_markup=await ik_video_back_to_settings(),
    )


@router.message(VideoGenerationState.waiting_image, F.photo)
@router.message(VideoGenerationState.waiting_image, F.document, F.document.mime_type.startswith("image/"))
async def collect_video_image(
    message: Message,
    state: FSMContext,
) -> None:
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    else:
        return

    data = await update_video_data(state, image_file_id=file_id)
    await state.set_state(VideoGenerationState.settings)
    await message.answer(
        video_settings_text(data),
        reply_markup=await ik_video_settings(
            model_key=data.model_key,
            duration=data.duration,
            aspect_ratio=data.aspect_ratio,
            with_audio=data.with_audio,
        ),
    )


@router.callback_query(VideoNav.filter(F.action == "back_to_settings"))
async def back_to_settings(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    await _open_settings(query, state)


@router.callback_query(VideoNav.filter(F.action == "generate"))
async def start_video_generation(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    await query.answer()
    data = await get_video_data(state)

    if not data.prompt.strip():
        await query.answer("Сначала укажите промпт для видео.", show_alert=True)
        return

    model = get_kling_model(data.model_key)
    cost = video_cost(data.model_key, data.duration)

    if user.credits < cost:
        await query.answer(
            f"Недостаточно кредитов. Нужно: {cost}, у вас: {user.credits}",
            show_alert=True,
        )
        return

    task_id = uuid.uuid4().hex[:8]
    if query.message and isinstance(query.message, Message):
        status_msg = await query.message.answer(
            f"🎬 Генерация видео запущена!\n"
            f"🆔 Задача: {task_id}\n"
            f"📹 Модель: {model.title}\n"
            f"⏱ Длительность: {data.duration} сек.\n"
            f"📐 Формат: {data.aspect_ratio}\n"
            "Это займёт некоторое время, я пришлю результат."
        )
    else:
        return

    reference_image: str | None = None
    if data.image_file_id and query.message.bot:
        try:
            bot = query.message.bot
            file = await bot.get_file(data.image_file_id)
            if file.file_path:
                bot_token = getattr(bot, "token", "")
                url = f"https://api.telegram.org/file/bot{bot_token}/{file.file_path}"
                timeout = aiohttp.ClientTimeout(total=60)
                async with aiohttp.ClientSession(timeout=timeout) as http_session:
                    async with http_session.get(url) as response:
                        img_bytes = await response.read()
                reference_image = (
                    "data:image/jpeg;base64,"
                    + base64.b64encode(img_bytes).decode("ascii")
                )
        except Exception:
            logger.exception("Failed to prepare reference image for video")

    try:
        video_bytes = await generate_video(
            prompt=data.prompt.strip(),
            runware_model=model.runware_model,
            duration=data.duration,
            aspect_ratio=data.aspect_ratio,
            with_audio=data.with_audio,
            reference_image=reference_image,
        )
        await deduct_user_credits(
            session=session,
            redis=redis,
            user_id=user.user_id,
            amount=cost,
        )
        filename = f"video_{task_id}.mp4"
        await query.message.answer_document(
            document=BufferedInputFile(file=video_bytes, filename=filename),
            caption=(
                f"🎬 Готово!\n"
                f"📹 Модель: {model.title}\n"
                f"⏱ Длительность: {data.duration} сек.\n"
                f"💰 Списано: {cost} кредитов"
            ),
            reply_markup=await ik_back_home(),
        )
        await status_msg.delete()

    except VideoGenerationTimeoutError:
        await status_msg.edit_text(
            "❌ Генерация видео заняла слишком много времени.\n\n"
            "Попробуйте ещё раз чуть позже."
        )
    except VideoGenerationError as e:
        logger.exception("Video generation error")
        await status_msg.edit_text(
            "❌ Не удалось сгенерировать видео.\n\nПопробуйте ещё раз чуть позже."
        )
        if query.message.bot:
            await notify_admins_error(
                query.message.bot,
                "Ошибка генерации видео (Kling)",
                e,
                context={
                    "user_id": user.user_id,
                    "model": model.runware_model,
                    "duration": data.duration,
                    "prompt": data.prompt[:200],
                },
            )
    except Exception as e:
        logger.exception("Unexpected video generation error")
        await status_msg.edit_text(
            "❌ Не удалось сгенерировать видео.\n\nПопробуйте ещё раз чуть позже."
        )
        if query.message.bot:
            await notify_admins_error(
                query.message.bot,
                "Неожиданная ошибка генерации видео",
                e,
                context={
                    "user_id": user.user_id,
                    "model": model.runware_model,
                },
            )
