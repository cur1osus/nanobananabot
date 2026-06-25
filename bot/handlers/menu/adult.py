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
    ik_create_aspect_ratio,
    ik_image_waiting_photos,
)
from bot.states import ImageGenerationState
from bot.utils.image_models import DEFAULT_ADULT_IMAGE_MODEL_KEY
from bot.utils.image_state import update_image_data
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import (
    ADULT_CONSENT_TEXT,
    ADULT_MENU_TEXT,
    CREATE_ASPECT_RATIO_TEXT,
    PHOTO_REQUEST_TEXT,
)

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
    # Модель в 18+ одна — выбор не показываем, сразу к формату и промпту.
    await state.clear()
    await update_image_data(
        state,
        model_key=DEFAULT_ADULT_IMAGE_MODEL_KEY,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    await state.set_state(ImageGenerationState.waiting_create_aspect)
    await query.answer()
    await edit_or_answer(
        query,
        text=CREATE_ASPECT_RATIO_TEXT,
        reply_markup=await ik_create_aspect_ratio(is_adult=True),
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
    # Модель в 18+ одна — выбор не показываем, сразу просим фото.
    await state.clear()
    await update_image_data(
        state,
        model_key=DEFAULT_ADULT_IMAGE_MODEL_KEY,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    await state.set_state(ImageGenerationState.waiting_photos)
    await query.answer()
    await edit_or_answer(
        query,
        text=PHOTO_REQUEST_TEXT,
        reply_markup=await ik_image_waiting_photos(is_adult=True),
    )
