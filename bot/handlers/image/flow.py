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
from bot.keyboards.factories import ModelMenu, ModelSelect
from bot.keyboards.inline import (
    ik_back_home,
    ik_image_model_select,
    ik_image_waiting_photos,
)
from bot.states import ImageGenerationState
from bot.utils.image_models import (
    DEFAULT_IMAGE_MODEL_KEY,
    get_image_model,
    is_image_model_key,
)
from bot.utils.image_state import get_image_data, update_image_data
from bot.utils.image_tasks import ImageGenerationError, generate_image
from bot.utils.messaging import edit_or_answer
from bot.utils.speech_recognition import (
    SpeechRecognitionError,
    transcribe_message_audio,
)
from bot.utils.texts import (
    PHOTO_REQUEST_TEXT,
    PROMPT_REQUEST_TEXT,
    generation_started_text,
    model_panel_text,
)

router = Router()
logger = logging.getLogger(__name__)

MAX_PHOTOS = 4


async def _download_telegram_file(bot_token: str, file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()


async def _build_reference_images(message: Message, photo_ids: list[str]) -> list[str]:
    bot = message.bot
    if bot is None:
        return []

    bot_token = getattr(bot, "token", "")
    if not bot_token:
        return []

    image_urls: list[str] = []
    for file_id in photo_ids[:MAX_PHOTOS]:
        try:
            file = await bot.get_file(file_id)
            if not file.file_path:
                continue
            image_bytes = await _download_telegram_file(bot_token, file.file_path)
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            image_urls.append(f"data:image/jpeg;base64,{image_b64}")
        except Exception:
            logger.exception("Failed to prepare image reference: file_id=%s", file_id)

    return image_urls


def _generation_error_text(error: Exception) -> str:
    details = str(error).strip()
    if details:
        details = details[:350]
        return f"❌ Ошибка при генерации изображения.\n\nДетали API: {details}"
    return (
        "❌ Ошибка при генерации изображения. Попробуйте позже.\n\n"
        "Если ошибка повторяется, обратитесь в поддержку."
    )


@router.callback_query(ModelMenu.filter())
async def open_model_menu(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await edit_or_answer(
        query,
        text=model_panel_text(user, selected_key),
        reply_markup=await ik_image_model_select(selected_key),
    )


@router.callback_query(ModelSelect.filter())
async def select_model(
    query: CallbackQuery,
    callback_data: ModelSelect,
    state: FSMContext,
    user: UserRD,
) -> None:
    if not is_image_model_key(callback_data.model):
        await query.answer("Неизвестная модель", show_alert=True)
        return

    model = get_image_model(callback_data.model)
    if user.credits < model.cost:
        await query.answer(
            f"Недостаточно кредитов. Нужно: {model.cost}, у вас: {user.credits}",
            show_alert=True,
        )
        return

    await update_image_data(
        state,
        model_key=callback_data.model,
        photos=[],
        prompt="",
        prompt_requested=False,
    )
    await state.set_state(ImageGenerationState.waiting_photos)
    await edit_or_answer(
        query,
        text=f"{model_panel_text(user, callback_data.model)}\n\n{PHOTO_REQUEST_TEXT}",
        reply_markup=await ik_image_waiting_photos(),
    )
    await query.answer()


@router.message(ImageGenerationState.waiting_photos, F.text)
async def remind_photos(
    message: Message,
) -> None:
    await message.answer(PHOTO_REQUEST_TEXT)


@router.message(ImageGenerationState.waiting_photos, F.photo)
@router.message(ImageGenerationState.waiting_prompt, F.photo)
async def collect_photos(
    message: Message,
    state: FSMContext,
) -> None:
    data = await get_image_data(state)
    photos = list(data.photos)
    if len(photos) >= MAX_PHOTOS:
        await message.answer("Можно отправить максимум 4 фото.")
        return
    if not message.photo:
        return
    photos.append(message.photo[-1].file_id)

    prompt_requested = data.prompt_requested
    if not prompt_requested:
        prompt_requested = True
        await message.answer(PROMPT_REQUEST_TEXT)
        await state.set_state(ImageGenerationState.waiting_prompt)

    await update_image_data(state, photos=photos, prompt_requested=prompt_requested)

    if len(photos) >= MAX_PHOTOS:
        await message.answer("Получено 4 фото. Теперь пришлите текстовый промпт.")


@router.message(ImageGenerationState.waiting_prompt, F.text)
async def collect_prompt(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    prompt = message.text.strip() if message.text else ""
    if not prompt:
        await message.answer("Опишите запрос текстом.")
        return

    data = await get_image_data(state)
    if not data.photos:
        await state.set_state(ImageGenerationState.waiting_photos)
        await message.answer(PHOTO_REQUEST_TEXT)
        return

    model = get_image_model(data.model_key)

    # Check credits again before generating
    if user.credits < model.cost:
        await message.answer(
            f"Недостаточно кредитов для генерации. Нужно: {model.cost}, у вас: {user.credits}",
            reply_markup=await ik_back_home(),
        )
        await state.set_state(ImageGenerationState.waiting_photos)
        return

    # Generate task ID and send "generating" message
    task_id = uuid.uuid4().hex[:8]
    status_msg = await message.answer(generation_started_text(task_id, data.model_key))

    try:
        reference_images = await _build_reference_images(message, data.photos)

        # Generate image
        image_bytes = await generate_image(
            prompt=prompt,
            reference_images=reference_images,
            aspect_ratio="1:1",
            output_format="jpeg",
        )

        # Deduct credits
        await deduct_user_credits(
            session=session,
            redis=redis,
            user_id=user.user_id,
            amount=model.cost,
        )

        # Send image to user
        input_file = BufferedInputFile(
            file=image_bytes, filename=f"generated_{data.model_key}.jpg"
        )
        await message.answer_photo(
            photo=input_file,
            caption=f"✅ Готово!\n🎨 Модель: {model.title}\n💰 Списано: {model.cost} кредитов",
            reply_markup=await ik_back_home(),
        )

        # Delete status message
        await status_msg.delete()

    except ImageGenerationError as e:
        logger.exception("Image generation API error")
        await status_msg.edit_text(_generation_error_text(e))
    except Exception as e:
        logger.exception("Unexpected image generation error")
        await status_msg.edit_text(_generation_error_text(e))

    # Reset state
    await update_image_data(state, prompt="", prompt_requested=False, photos=[])
    await state.set_state(ImageGenerationState.waiting_photos)


@router.message(ImageGenerationState.waiting_prompt, F.voice | F.audio)
async def collect_prompt_voice(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    """Handle voice/audio messages for image generation prompt."""
    # Send processing message
    processing_msg = await message.answer("🎙️ Распознаю голосовое сообщение...")

    try:
        # Transcribe audio
        prompt = await transcribe_message_audio(message, language="ru")

        if not prompt:
            await processing_msg.edit_text(
                "Не удалось распознать голосовое сообщение. Попробуйте еще раз или введите текстом."
            )
            return

        # Delete processing message
        await processing_msg.delete()

        # Show recognized text
        await message.answer(f"📝 Распознано: {prompt}")

        # Now process the prompt same as text
        data = await get_image_data(state)
        if not data.photos:
            await state.set_state(ImageGenerationState.waiting_photos)
            await message.answer(PHOTO_REQUEST_TEXT)
            return

        model = get_image_model(data.model_key)

        # Check credits
        if user.credits < model.cost:
            await message.answer(
                f"Недостаточно кредитов для генерации. Нужно: {model.cost}, у вас: {user.credits}",
                reply_markup=await ik_back_home(),
            )
            await state.set_state(ImageGenerationState.waiting_photos)
            return

        # Generate task ID and send "generating" message
        task_id = uuid.uuid4().hex[:8]
        status_msg = await message.answer(
            generation_started_text(task_id, data.model_key)
        )

        try:
            reference_images = await _build_reference_images(message, data.photos)

            # Generate image
            image_bytes = await generate_image(
                prompt=prompt,
                reference_images=reference_images,
                aspect_ratio="1:1",
                output_format="jpeg",
            )

            # Deduct credits
            await deduct_user_credits(
                session=session,
                redis=redis,
                user_id=user.user_id,
                amount=model.cost,
            )

            # Send image to user
            input_file = BufferedInputFile(
                file=image_bytes, filename=f"generated_{data.model_key}.jpg"
            )
            await message.answer_photo(
                photo=input_file,
                caption=f"✅ Готово!\n🎨 Модель: {model.title}\n💰 Списано: {model.cost} кредитов",
                reply_markup=await ik_back_home(),
            )

            # Delete status message
            await status_msg.delete()

        except ImageGenerationError as e:
            logger.exception("Image generation API error (voice prompt)")
            await status_msg.edit_text(_generation_error_text(e))
        except Exception as e:
            logger.exception("Unexpected image generation error (voice prompt)")
            await status_msg.edit_text(_generation_error_text(e))

        # Reset state
        await update_image_data(state, prompt="", prompt_requested=False, photos=[])
        await state.set_state(ImageGenerationState.waiting_photos)

    except SpeechRecognitionError as e:
        await processing_msg.edit_text(
            f"❌ Ошибка распознавания: {e}\n\nПопробуйте ввести текстом."
        )
    except Exception:
        await processing_msg.edit_text(
            "❌ Произошла ошибка при обработке голосового сообщения. Попробуйте ввести текстом."
        )
