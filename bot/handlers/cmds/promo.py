from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.states import PromoState
from bot.utils.promo import (
    PromoResult,
    create_promo_code,
    redeem_promo_code,
)

router = Router()
logger = logging.getLogger(__name__)

_RESULT_MESSAGES = {
    PromoResult.NOT_FOUND: "❌ Промокод не найден или неактивен.",
    PromoResult.EXPIRED: "⌛ Срок действия промокода истёк.",
    PromoResult.EXHAUSTED: "🚫 Лимит активаций промокода исчерпан.",
    PromoResult.ALREADY_USED: "ℹ️ Вы уже активировали этот промокод.",
    PromoResult.ERROR: "⚠️ Не удалось активировать промокод. Попробуйте позже.",
}

ENTER_CODE_TEXT = "🎁 Введите промокод одним сообщением:"


async def _apply_code(
    message: Message,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
    code: str,
) -> None:
    result, credits = await redeem_promo_code(
        session=session, redis=redis, user=user, code=code
    )
    if result is PromoResult.OK:
        await message.answer(f"✅ Промокод активирован! Начислено {credits} кредитов.")
        return
    await message.answer(
        _RESULT_MESSAGES.get(result, _RESULT_MESSAGES[PromoResult.ERROR])
    )


@router.message(Command("promo"))
async def cmd_promo(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    code = (command.args or "").strip()
    if not code:
        await state.set_state(PromoState.waiting_code)
        await message.answer(ENTER_CODE_TEXT)
        return
    await state.clear()
    await _apply_code(message, user, session, redis, code)


@router.callback_query(MenuAction.filter(F.action == "promo"))
async def menu_promo(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(PromoState.waiting_code)
    if isinstance(query.message, Message):
        await query.message.answer(ENTER_CODE_TEXT)


@router.message(PromoState.waiting_code, F.text)
async def promo_code_input(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    await state.clear()
    await _apply_code(message, user, session, redis, message.text or "")


# ─── Создание промокода (админ-панель, без публичной команды) ─────────────────

CREATE_PROMPT_TEXT = (
    "🎟 Создание промокода. Пришлите одной строкой:\n"
    "<code>КОД КРЕДИТЫ [МАКС_АКТИВАЦИЙ] [СРОК_ДНЕЙ]</code>\n\n"
    "• МАКС_АКТИВАЦИЙ = 0 или отсутствует — без лимита\n"
    "• СРОК_ДНЕЙ отсутствует — бессрочно\n\n"
    "Пример: <code>WELCOME 10 100 7</code>"
)


@router.callback_query(MenuAction.filter(F.action == "promo_new"))
async def menu_promo_new(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    if user.role != UserRole.ADMIN.value:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(PromoState.waiting_create)
    if isinstance(query.message, Message):
        await query.message.answer(CREATE_PROMPT_TEXT)


@router.message(PromoState.waiting_create, F.text)
async def promo_create_input(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
) -> None:
    if user.role != UserRole.ADMIN.value:
        await state.clear()
        await message.answer("У вас нет прав на выполнение этой операции.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Нужно минимум КОД и КРЕДИТЫ. Пример: WELCOME 10 100 7")
        return

    code = parts[0]
    if not parts[1].isdigit() or int(parts[1]) <= 0:
        await message.answer("КРЕДИТЫ должны быть положительным числом.")
        return
    credits = int(parts[1])

    max_activations = 0
    if len(parts) >= 3:
        if not parts[2].isdigit():
            await message.answer("МАКС_АКТИВАЦИЙ должно быть числом (0 = без лимита).")
            return
        max_activations = int(parts[2])

    expires_at: datetime | None = None
    if len(parts) >= 4:
        if not parts[3].isdigit() or int(parts[3]) <= 0:
            await message.answer("СРОК_ДНЕЙ должен быть положительным числом.")
            return
        expires_at = (datetime.now(UTC) + timedelta(days=int(parts[3]))).replace(
            tzinfo=None
        )

    created = await create_promo_code(
        session=session,
        code=code,
        credits=credits,
        max_activations=max_activations,
        expires_at=expires_at,
        created_by=user.user_id,
    )
    await state.clear()
    if not created:
        await message.answer("Промокод с таким кодом уже существует.")
        return

    limit_txt = "без лимита" if max_activations == 0 else f"{max_activations} активаций"
    expiry_txt = f"до {expires_at:%d.%m.%Y}" if expires_at else "бессрочно"
    await message.answer(
        f"✅ Промокод создан.\n"
        f"Код: {code.upper()}\n"
        f"Кредиты: {credits}\n"
        f"Лимит: {limit_txt}\n"
        f"Срок: {expiry_txt}"
    )
