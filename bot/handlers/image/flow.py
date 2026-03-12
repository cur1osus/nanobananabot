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
from bot.keyboards.factories import (
    CreateAspectRatio,
    ImageNav,
    ImageResultAction,
    ModelMenu,
    ModelSelect,
)
from bot.keyboards.inline import (
    ik_back_home,
    ik_create_aspect_ratio,
    ik_create_prompt_nav,
    ik_image_model_select,
    ik_image_result_actions,
    ik_image_waiting_photos,
    ik_prompt_nav,
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
    CREATE_ASPECT_RATIO_TEXT,
    CREATE_PROMPT_TEXT,
    PROMPT_REQUEST_TEXT,
    generation_started_text,
    model_panel_text,
)

router = Router()
logger = logging.getLogger(__name__)

DEFAULT_MAX_REFERENCES = 4
NANO2_MAX_REFERENCES = 8

CREATE_RATIO_MAP: dict[str, str] = {
    "auto": "auto",
    "21x9": "21:9",
    "16x9": "16:9",
    "3x2": "3:2",
    "4x3": "4:3",
    "5x4": "5:4",
    "1x1": "1:1",
    "4x5": "4:5",
    "3x4": "3:4",
    "2x3": "2:3",
    "9x16": "9:16",
}


def _photo_limit_for_model(model_key: str) -> int:
    if model_key == "nano2":
        return NANO2_MAX_REFERENCES
    return DEFAULT_MAX_REFERENCES


def _photo_request_text(model_key: str) -> str:
    max_refs = _photo_limit_for_model(model_key)
    return f"Пришлите 1-{max_refs} фотографий которые нужно изменить или объединить"


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
    for file_id in photo_ids[:10]:
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


async def _send_generation_result(
    message: Message,
    *,
    image_bytes: bytes,
    model_key: str,
    model_title: str,
    model_cost: int,
    task_id: str,
    show_result_actions: bool = True,
) -> None:
    filename = f"generation_{task_id}_{model_key}.jpg"
    await message.answer_document(
        document=BufferedInputFile(file=image_bytes, filename=filename),
        caption="📎 Файл результата",
    )
    await message.answer_photo(
        photo=BufferedInputFile(file=image_bytes, filename="preview.jpg"),
        caption=f"✅ Готово!\n🎨 Модель: {model_title}\n💰 Списано: {model_cost} кредитов",
        reply_markup=(
            await ik_image_result_actions()
            if show_result_actions
            else await ik_back_home()
        ),
    )


async def _run_image_generation(
    *,
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
    prompt: str,
) -> None:
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        await message.answer("Опишите запрос текстом.")
        return

    data = await get_image_data(state)
    if not data.photos:
        await state.set_state(ImageGenerationState.waiting_photos)
        await message.answer(_photo_request_text(data.model_key))
        return

    model = get_image_model(data.model_key)
    if user.credits < model.cost:
        await message.answer(
            f"Недостаточно кредитов для генерации. Нужно: {model.cost}, у вас: {user.credits}",
            reply_markup=await ik_back_home(),
        )
        await state.set_state(ImageGenerationState.waiting_photos)
        return

    task_id = uuid.uuid4().hex[:8]
    status_msg = await message.answer(generation_started_text(task_id, data.model_key))

    try:
        reference_images = await _build_reference_images(message, data.photos)
        image_bytes = await generate_image(
            prompt=normalized_prompt,
            model=model.api_model,
            reference_images=reference_images,
            aspect_ratio=data.aspect_ratio,
            output_format="jpeg",
        )
        await deduct_user_credits(
            session=session,
            redis=redis,
            user_id=user.user_id,
            amount=model.cost,
        )
        await _send_generation_result(
            message,
            image_bytes=image_bytes,
            model_key=data.model_key,
            model_title=model.title,
            model_cost=model.cost,
            task_id=task_id,
        )
        await update_image_data(
            state,
            prompt=normalized_prompt,
            prompt_requested=True,
        )
        await state.set_state(ImageGenerationState.waiting_prompt)
        await status_msg.delete()
    except ImageGenerationError as e:
        logger.exception("Image generation API error")
        await status_msg.edit_text(_generation_error_text(e))
    except Exception as e:
        logger.exception("Unexpected image generation error")
        await status_msg.edit_text(_generation_error_text(e))


async def _run_create_generation(
    *,
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
    prompt: str,
) -> None:
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        await message.answer("Опишите запрос текстом.")
        return

    data = await get_image_data(state)
    model = get_image_model(data.model_key)
    if user.credits < model.cost:
        await message.answer(
            f"Недостаточно кредитов для генерации. Нужно: {model.cost}, у вас: {user.credits}",
            reply_markup=await ik_back_home(),
        )
        return

    task_id = uuid.uuid4().hex[:8]
    status_msg = await message.answer(generation_started_text(task_id, data.model_key))

    try:
        image_bytes = await generate_image(
            prompt=normalized_prompt,
            model=model.create_api_model,
            reference_images=None,
            aspect_ratio=data.aspect_ratio,
            output_format="jpeg",
        )
        await deduct_user_credits(
            session=session,
            redis=redis,
            user_id=user.user_id,
            amount=model.cost,
        )
        await _send_generation_result(
            message,
            image_bytes=image_bytes,
            model_key=data.model_key,
            model_title=model.title,
            model_cost=model.cost,
            task_id=task_id,
            show_result_actions=False,
        )
        await update_image_data(
            state,
            prompt=normalized_prompt,
            photos=[],
            prompt_requested=True,
        )
        await state.set_state(ImageGenerationState.waiting_create_prompt)
        await status_msg.delete()
    except ImageGenerationError as e:
        logger.exception("Create image API error")
        await status_msg.edit_text(_generation_error_text(e))
    except Exception as e:
        logger.exception("Unexpected create image error")
        await status_msg.edit_text(_generation_error_text(e))


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

    current_state = await state.get_state()

    await update_image_data(
        state,
        model_key=callback_data.model,
        photos=[],
        aspect_ratio="auto",
        prompt="",
        prompt_requested=False,
    )

    if current_state == ImageGenerationState.waiting_create_model.state:
        await state.set_state(ImageGenerationState.waiting_create_aspect)
        await edit_or_answer(
            query,
            text=CREATE_ASPECT_RATIO_TEXT,
            reply_markup=await ik_create_aspect_ratio(),
        )
    else:
        await state.set_state(ImageGenerationState.waiting_photos)
        await edit_or_answer(
            query,
            text=(
                f"{model_panel_text(user, callback_data.model)}\n\n"
                f"{_photo_request_text(callback_data.model)}"
            ),
            reply_markup=await ik_image_waiting_photos(),
        )
    await query.answer()


@router.message(ImageGenerationState.waiting_create_model)
async def remind_create_model(
    message: Message,
    state: FSMContext,
    user: UserRD,
) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await message.answer(
        model_panel_text(user, selected_key),
        reply_markup=await ik_image_model_select(selected_key),
    )


@router.message(ImageGenerationState.waiting_photos, F.text)
async def remind_photos(
    message: Message,
    state: FSMContext,
) -> None:
    data = await get_image_data(state)
    await message.answer(
        _photo_request_text(data.model_key),
        reply_markup=await ik_image_waiting_photos(),
    )


@router.callback_query(ImageNav.filter())
async def handle_image_nav(
    query: CallbackQuery,
    callback_data: ImageNav,
    state: FSMContext,
    user: UserRD,
) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY

    if callback_data.action == "to_photos":
        await state.set_state(ImageGenerationState.waiting_photos)
        await query.answer()
        await edit_or_answer(
            query,
            text=_photo_request_text(selected_key),
            reply_markup=await ik_image_waiting_photos(),
        )
        return

    if callback_data.action == "to_create_aspect":
        await state.set_state(ImageGenerationState.waiting_create_aspect)
        await query.answer()
        await edit_or_answer(
            query,
            text=CREATE_ASPECT_RATIO_TEXT,
            reply_markup=await ik_create_aspect_ratio(),
        )
        return

    await query.answer("Неизвестное действие", show_alert=True)


@router.callback_query(ImageResultAction.filter())
async def handle_result_actions(
    query: CallbackQuery,
    callback_data: ImageResultAction,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    data = await get_image_data(state)

    if callback_data.action == "similar":
        if not data.photos or not data.prompt:
            await query.answer("Нет данных прошлой генерации", show_alert=True)
            return
        await query.answer()
        if isinstance(query.message, Message):
            await _run_image_generation(
                message=query.message,
                state=state,
                user=user,
                session=session,
                redis=redis,
                prompt=data.prompt,
            )
        return

    if callback_data.action == "first_photo":
        if not data.photos:
            await query.answer("Нет сохраненных фото", show_alert=True)
            return
        await update_image_data(
            state,
            photos=[data.photos[0]],
            prompt="",
            prompt_requested=True,
        )
        await state.set_state(ImageGenerationState.waiting_prompt)
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.answer(
                "Оставил 1-е фото. Теперь пришлите новый промпт."
            )
        return

    if callback_data.action == "restart":
        await update_image_data(
            state,
            photos=[],
            prompt="",
            prompt_requested=False,
            aspect_ratio="auto",
        )
        await state.set_state(ImageGenerationState.waiting_photos)
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.answer(
                _photo_request_text(data.model_key),
                reply_markup=await ik_image_waiting_photos(),
            )
        return

    await query.answer("Неизвестное действие", show_alert=True)


@router.message(ImageGenerationState.waiting_photos, F.photo)
@router.message(ImageGenerationState.waiting_prompt, F.photo)
async def collect_photos(
    message: Message,
    state: FSMContext,
) -> None:
    data = await get_image_data(state)
    photos = list(data.photos)
    max_references = _photo_limit_for_model(data.model_key)
    if len(photos) >= max_references:
        await message.answer(f"Можно отправить максимум {max_references} фото.")
        return
    if not message.photo:
        return
    photo = message.photo[-1]
    photos.append(photo.file_id)
    aspect_ratio = data.aspect_ratio
    if len(photos) == 1:
        aspect_ratio = "auto"

    prompt_requested = data.prompt_requested
    if not prompt_requested:
        prompt_requested = True
        await message.answer(
            PROMPT_REQUEST_TEXT,
            reply_markup=await ik_prompt_nav(),
        )
        await state.set_state(ImageGenerationState.waiting_prompt)

    await update_image_data(
        state,
        photos=photos,
        aspect_ratio=aspect_ratio,
        prompt_requested=prompt_requested,
    )

    if len(photos) >= max_references:
        await message.answer(
            f"Получено {max_references} фото. Теперь пришлите текстовый промпт."
        )


@router.message(ImageGenerationState.waiting_prompt, F.text)
async def collect_prompt(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    await _run_image_generation(
        message=message,
        state=state,
        user=user,
        session=session,
        redis=redis,
        prompt=message.text or "",
    )


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

        await _run_image_generation(
            message=message,
            state=state,
            user=user,
            session=session,
            redis=redis,
            prompt=prompt,
        )

    except SpeechRecognitionError as e:
        await processing_msg.edit_text(
            f"❌ Ошибка распознавания: {e}\n\nПопробуйте ввести текстом."
        )
    except Exception:
        await processing_msg.edit_text(
            "❌ Произошла ошибка при обработке голосового сообщения. Попробуйте ввести текстом."
        )


@router.message(ImageGenerationState.waiting_create_aspect)
async def remind_create_aspect(message: Message) -> None:
    await message.answer(
        "Выберите соотношение сторон кнопками ниже.",
        reply_markup=await ik_create_aspect_ratio(),
    )


@router.callback_query(
    ImageGenerationState.waiting_create_aspect, CreateAspectRatio.filter()
)
async def select_create_aspect_ratio(
    query: CallbackQuery,
    callback_data: CreateAspectRatio,
    state: FSMContext,
) -> None:
    aspect_ratio = CREATE_RATIO_MAP.get(callback_data.ratio)
    if not aspect_ratio:
        await query.answer("Неизвестное соотношение", show_alert=True)
        return

    await update_image_data(
        state,
        photos=[],
        prompt="",
        prompt_requested=True,
        aspect_ratio=aspect_ratio,
    )
    await state.set_state(ImageGenerationState.waiting_create_prompt)
    await query.answer()
    await edit_or_answer(
        query,
        text=CREATE_PROMPT_TEXT,
        reply_markup=await ik_create_prompt_nav(),
    )


@router.message(ImageGenerationState.waiting_create_prompt, F.photo)
async def remind_create_prompt_photo(message: Message) -> None:
    await message.answer(
        "В режиме создания фото не нужны. Пришлите только текстовый промпт.",
        reply_markup=await ik_create_prompt_nav(),
    )


@router.message(ImageGenerationState.waiting_create_prompt, F.text)
async def collect_create_prompt(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    await _run_create_generation(
        message=message,
        state=state,
        user=user,
        session=session,
        redis=redis,
        prompt=message.text or "",
    )


@router.message(ImageGenerationState.waiting_create_prompt, F.voice | F.audio)
async def collect_create_prompt_voice(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    processing_msg = await message.answer("🎙️ Распознаю голосовое сообщение...")

    try:
        prompt = await transcribe_message_audio(message, language="ru")
        if not prompt:
            await processing_msg.edit_text(
                "Не удалось распознать голосовое сообщение. Попробуйте еще раз или введите текстом."
            )
            return

        await processing_msg.delete()
        await message.answer(f"📝 Распознано: {prompt}")
        await _run_create_generation(
            message=message,
            state=state,
            user=user,
            session=session,
            redis=redis,
            prompt=prompt,
        )
    except SpeechRecognitionError as e:
        await processing_msg.edit_text(
            f"❌ Ошибка распознавания: {e}\n\nПопробуйте ввести текстом."
        )
    except Exception:
        await processing_msg.edit_text(
            "❌ Произошла ошибка при обработке голосового сообщения. Попробуйте ввести текстом."
        )
