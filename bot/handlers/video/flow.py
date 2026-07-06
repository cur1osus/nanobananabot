from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import GenerationKind
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import VideoAspectRatio, VideoNav, VideoSetting
from bot.keyboards.inline import (
    ik_video_back_to_settings,
    ik_video_settings,
)
from bot.states import VideoGenerationState
from bot.utils.billing import (
    CreditsExhausted,
    GenerationBusy,
    enqueue_generation,
)
from bot.utils.messaging import edit_or_answer
from bot.utils.video_models import (
    DEFAULT_VIDEO_DURATION,
    VIDEO_RATIO_MAP,
    get_kling_model,
    video_cost,
)
from bot.utils.video_state import (
    VideoFlowData,
    get_video_data,
    update_video_data,
    video_settings_text,
)

router = Router()
logger = logging.getLogger(__name__)


async def _settings_markup(data: VideoFlowData):
    return await ik_video_settings(
        model_key=data.model_key,
        duration=data.duration,
        aspect_ratio=data.aspect_ratio,
        with_audio=data.with_audio,
        has_image=bool(data.image_file_id),
    )


async def _open_settings(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await get_video_data(state)
    await state.set_state(VideoGenerationState.settings)
    await edit_or_answer(
        query,
        text=video_settings_text(data),
        reply_markup=await _settings_markup(data),
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
            if d in get_kling_model(data.model_key).durations:
                data.duration = d
        except ValueError:
            pass

    elif callback_data.setting == "audio":
        data.with_audio = callback_data.value == "1"

    elif callback_data.setting == "quality4k":
        from bot.utils.video_models import (
            KLING_4K_BASE_MODEL_KEY,
            KLING_4K_MODEL_KEY,
        )

        data.model_key = (
            KLING_4K_MODEL_KEY
            if callback_data.value == "1"
            else KLING_4K_BASE_MODEL_KEY
        )

    # После смены модели длительность может стать недоступной — сбрасываем.
    new_model = get_kling_model(data.model_key)
    if new_model.supports_duration and data.duration not in new_model.durations:
        data.duration = DEFAULT_VIDEO_DURATION

    from bot.utils.video_state import set_video_data

    await set_video_data(state, data)
    await state.set_state(VideoGenerationState.settings)

    await edit_or_answer(
        query,
        text=video_settings_text(data),
        reply_markup=await _settings_markup(data),
    )


@router.callback_query(VideoAspectRatio.filter())
async def handle_video_ratio(
    query: CallbackQuery,
    callback_data: VideoAspectRatio,
    state: FSMContext,
) -> None:
    await query.answer()
    ratio = VIDEO_RATIO_MAP.get(callback_data.ratio)
    if ratio:
        data = await update_video_data(state, aspect_ratio=ratio)
        await state.set_state(VideoGenerationState.settings)
        await edit_or_answer(
            query,
            text=video_settings_text(data),
            reply_markup=await ik_video_settings(
                model_key=data.model_key,
                duration=data.duration,
                aspect_ratio=data.aspect_ratio,
                with_audio=data.with_audio,
                has_image=bool(data.image_file_id),
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
        reply_markup=await _settings_markup(data),
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
@router.message(
    VideoGenerationState.waiting_image,
    F.document,
    F.document.mime_type.startswith("image/"),
)
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
        reply_markup=await _settings_markup(data),
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

    if not (query.message and isinstance(query.message, Message)):
        return

    display_id = uuid.uuid4().hex[:8]
    status_msg = await query.message.answer(
        f"🎬 Генерация видео запущена!\n"
        f"🆔 Задача: {display_id}\n"
        f"📹 Модель: {model.title}\n"
        f"⏱ Длительность: {data.duration} сек.\n"
        f"📐 Формат: {data.aspect_ratio}\n"
        "Это займёт некоторое время, я пришлю результат."
    )

    # Референс скачивает воркер по сохранённому file_id — он переживает рестарт.
    try:
        await enqueue_generation(
            session=session,
            redis=redis,
            user=user,
            kind=GenerationKind.VIDEO.value,
            cost=cost,
            chat_id=query.message.chat.id,
            status_message_id=status_msg.message_id,
            params={
                "model_key": data.model_key,
                "prompt": data.prompt.strip(),
                "aspect_ratio": data.aspect_ratio,
                "duration": data.duration,
                "with_audio": data.with_audio,
                "image_file_id": data.image_file_id or "",
            },
        )
    except GenerationBusy:
        await status_msg.edit_text(
            "⏳ Достигнут лимит одновременных генераций (3). Дождитесь завершения одной из них и попробуйте снова."
        )
    except CreditsExhausted:
        await status_msg.edit_text(f"Недостаточно кредитов. Нужно: {cost}.")
    except Exception:
        logger.exception("Не удалось поставить генерацию видео в очередь")
        await status_msg.edit_text(
            "❌ Не удалось запустить генерацию. Попробуйте ещё раз."
        )
