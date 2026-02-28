from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("refund"))
async def refund_cmd(
    message: Message,
    user: UserRD,
) -> None:
    if user.role != UserRole.ADMIN.value:
        await message.answer("У вас нет прав на выполнение этой команды.")
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await message.answer(
            "Использование:\n/refund [user_id] [charge_id] - возврат звёзд пользователю"
        )
        return

    if not parts[1].isdigit():
        await message.answer("user_id должен быть числом.")
        return

    target_user_id = int(parts[1])
    telegram_charge_id = parts[2]

    try:
        refunded = await message.bot.refund_star_payment(
            user_id=target_user_id,
            telegram_payment_charge_id=telegram_charge_id,
        )
    except Exception as err:
        logger.warning("Ошибка при возврате звезд: %s", err)
        await message.answer(f"Не удалось вернуть платеж: {err}")
        return

    if not refunded:
        await message.answer("Возврат не выполнен. Попробуйте позже.")
        return

    await message.answer(
        f"Возврат выполнен.\n"
        f"Пользователь: {target_user_id}\n"
        f"Charge ID: {telegram_charge_id}"
    )
