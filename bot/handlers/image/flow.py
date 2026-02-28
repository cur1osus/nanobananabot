from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import ModelMenu, ModelSelect
from bot.keyboards.inline import ik_image_model_select
from bot.states import ImageGenerationState
from bot.utils.image_models import DEFAULT_IMAGE_MODEL_KEY, is_image_model_key
from bot.utils.image_state import get_image_data, update_image_data
from bot.utils.image_tasks import enqueue_fake_image_task
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import (
    PHOTO_REQUEST_TEXT,
    PROMPT_REQUEST_TEXT,
    generation_started_text,
    model_panel_text,
)

router = Router()

MAX_PHOTOS = 4


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
        text=model_panel_text(user, callback_data.model),
        reply_markup=await ik_image_model_select(callback_data.model),
    )
    if query.message:
        await query.message.answer(PHOTO_REQUEST_TEXT)
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

    task_id = await enqueue_fake_image_task(
        model_key=data.model_key,
        prompt=prompt,
        photo_ids=data.photos,
    )
    await update_image_data(state, prompt="", prompt_requested=False, photos=[])
    await state.set_state(ImageGenerationState.processing)
    await message.answer(generation_started_text(task_id, data.model_key))
    await state.set_state(ImageGenerationState.waiting_photos)
