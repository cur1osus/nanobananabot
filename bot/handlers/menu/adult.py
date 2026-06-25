from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from redis.asyncio import Redis

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import (
    ik_adult_consent,
    ik_adult_menu,
    ik_model_select_for_key,
)
from bot.states import ImageGenerationState
from bot.utils.image_models import DEFAULT_ADULT_IMAGE_MODEL_KEY, is_adult_model_key
from bot.utils.image_state import get_image_data, update_image_data
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import ADULT_CONSENT_TEXT, ADULT_MENU_TEXT, model_panel_text

router = Router()

_ADULT_CONFIRM_KEY = "adult_ok:{user_id}"


def _is_adult_allowed(user: UserRD) -> bool:
    # Тестовый период: раздел 18+ открыт только админам.
    return user.role == UserRole.ADMIN.value


async def _is_adult_confirmed(redis: Redis, user_id: int) -> bool:
    return bool(await redis.get(_ADULT_CONFIRM_KEY.format(user_id=user_id)))


async def _guard(query: CallbackQuery, user: UserRD, redis: Redis) -> bool:
    """Проверка доступа + подтверждения возраста. True — можно продолжать."""
    if not _is_adult_allowed(user):
        await query.answer("Раздел временно недоступен", show_alert=True)
        return False
    if not await _is_adult_confirmed(redis, user.user_id):
        await query.answer()
        await edit_or_answer(
            query,
            text=ADULT_CONSENT_TEXT,
            reply_markup=await ik_adult_consent(),
        )
        return False
    return True


async def _adult_model_key(state: FSMContext) -> str:
    data = await get_image_data(state)
    return (
        data.model_key
        if is_adult_model_key(data.model_key)
        else DEFAULT_ADULT_IMAGE_MODEL_KEY
    )


async def _show_adult_menu(query: CallbackQuery) -> None:
    await edit_or_answer(
        query,
        text=ADULT_MENU_TEXT,
        reply_markup=await ik_adult_menu(),
    )


@router.callback_query(MenuAction.filter(F.action == "adult"))
async def menu_adult(
    query: CallbackQuery,
    user: UserRD,
    redis: Redis,
) -> None:
    if not await _guard(query, user, redis):
        return
    await query.answer()
    await _show_adult_menu(query)


@router.callback_query(MenuAction.filter(F.action == "adult_confirm"))
async def menu_adult_confirm(
    query: CallbackQuery,
    user: UserRD,
    redis: Redis,
) -> None:
    if not _is_adult_allowed(user):
        await query.answer("Раздел временно недоступен", show_alert=True)
        return
    await redis.set(_ADULT_CONFIRM_KEY.format(user_id=user.user_id), "1")
    await query.answer("Доступ подтверждён")
    await _show_adult_menu(query)


@router.callback_query(MenuAction.filter(F.action == "adult_create"))
async def menu_adult_create(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
    redis: Redis,
) -> None:
    if not await _guard(query, user, redis):
        return
    selected_key = await _adult_model_key(state)
    await state.clear()
    await update_image_data(
        state,
        model_key=selected_key,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    # Состояние waiting_create_model → выбор модели уведёт в txt2img-flow.
    await state.set_state(ImageGenerationState.waiting_create_model)
    await query.answer()
    await edit_or_answer(
        query,
        text=model_panel_text(user, selected_key),
        reply_markup=await ik_model_select_for_key(selected_key),
    )


@router.callback_query(MenuAction.filter(F.action == "adult_edit"))
async def menu_adult_edit(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
    redis: Redis,
) -> None:
    if not await _guard(query, user, redis):
        return
    selected_key = await _adult_model_key(state)
    await state.clear()
    await update_image_data(
        state,
        model_key=selected_key,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    # Без waiting_create_model выбор модели уведёт в img2img-flow (запрос фото).
    await query.answer()
    await edit_or_answer(
        query,
        text=model_panel_text(user, selected_key),
        reply_markup=await ik_model_select_for_key(selected_key),
    )
