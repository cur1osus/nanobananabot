from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import ik_image_model_select, ik_main, ik_video_settings
from bot.states import BaseUserState, ImageGenerationState, VideoGenerationState
from bot.utils.image_models import DEFAULT_IMAGE_MODEL_KEY
from bot.utils.image_state import get_image_data, update_image_data
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import main_menu_text, model_panel_text
from bot.utils.video_state import get_video_data, video_settings_text

router = Router()


@router.callback_query(MenuAction.filter(F.action == "home"))
async def menu_home(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    await state.set_state(BaseUserState.main)
    await edit_or_answer(
        query,
        text=main_menu_text(user),
        reply_markup=await ik_main(is_admin=user.role == UserRole.ADMIN.value),
    )


@router.callback_query(MenuAction.filter(F.action == "image"))
async def menu_image(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await state.clear()
    await update_image_data(
        state,
        model_key=selected_key,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    await state.set_state(ImageGenerationState.waiting_create_model)
    await query.answer()
    await edit_or_answer(
        query,
        text=model_panel_text(user, selected_key),
        reply_markup=await ik_image_model_select(selected_key),
    )


@router.callback_query(MenuAction.filter(F.action == "video"))
async def menu_video(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    await query.answer()
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


@router.callback_query(MenuAction.filter(F.action == "edit"))
async def menu_edit(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await state.clear()
    await update_image_data(
        state,
        model_key=selected_key,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    await query.answer()
    await edit_or_answer(
        query,
        text=model_panel_text(user, selected_key),
        reply_markup=await ik_image_model_select(selected_key),
    )
