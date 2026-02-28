from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import TransactionStatus, TransactionType
from bot.db.func import withdraw_user_balance
from bot.db.models import TransactionModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import ik_back_earn, ik_back_withdraw, ik_withdraw_manager
from bot.settings import se
from bot.states import WithdrawState
from bot.utils.formatting import format_rub
from bot.utils.messaging import edit_or_answer
from bot.utils.withdrawals import get_manager_loads, pick_manager_id

router = Router()
logger = logging.getLogger(__name__)

MIN_WITHDRAW_RUB = 1000
MIN_WITHDRAW_KOPEKS = MIN_WITHDRAW_RUB * 100


@router.callback_query(MenuAction.filter(F.action == "withdraw"))
async def menu_withdraw(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    if user.balance < MIN_WITHDRAW_KOPEKS:
        await state.clear()
        await edit_or_answer(
            query,
            text=(
                "Минимальная сумма для вывода — 1000 руб.\n"
                f"Сейчас доступно {format_rub(user.balance)} руб."
            ),
            reply_markup=await ik_back_earn(),
        )
        return

    await state.set_state(WithdrawState.amount)
    await edit_or_answer(
        query,
        text="Введите сумму вывода в рублях (минимум 1000):",
        reply_markup=await ik_back_earn(),
    )


@router.message(WithdrawState.amount)
async def withdraw_amount(
    message: Message,
    state: FSMContext,
    user: UserRD,
) -> None:
    raw = (message.text or "").strip().replace(" ", "")
    if not raw.isdigit():
        await message.answer(
            "Введите сумму цифрами, например 1500.",
            reply_markup=await ik_back_earn(),
        )
        return

    amount_rub = int(raw)
    amount_kopeks = amount_rub * 100
    if amount_kopeks < MIN_WITHDRAW_KOPEKS:
        await message.answer(
            "Минимальная сумма вывода — 1000 руб.",
            reply_markup=await ik_back_earn(),
        )
        return

    if amount_kopeks > user.balance:
        await message.answer(
            "Недостаточно средств для вывода указанной суммы.",
            reply_markup=await ik_back_earn(),
        )
        return

    await state.update_data(withdraw_amount=amount_kopeks)
    await state.set_state(WithdrawState.details)
    await message.answer(
        "Введите реквизиты для вывода (карта/телефон/банк):",
        reply_markup=await ik_back_withdraw(),
    )


@router.message(WithdrawState.details)
async def withdraw_details(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    details = (message.text or "").strip()
    if not details:
        await message.answer(
            "Реквизиты не должны быть пустыми.",
            reply_markup=await ik_back_withdraw(),
        )
        return

    data = await state.get_data()
    amount = int(data.get("withdraw_amount") or 0)
    if amount <= 0:
        await state.clear()
        await message.answer(
            "Не удалось определить сумму вывода. Начните заново.",
            reply_markup=await ik_back_earn(),
        )
        return

    if not await withdraw_user_balance(
        session=session,
        redis=redis,
        user=user,
        amount=amount,
    ):
        await message.answer(
            "Недостаточно средств для вывода. Проверьте баланс.",
            reply_markup=await ik_back_earn(),
        )
        await state.clear()
        return

    manager_id = await _select_manager_id(session)
    transaction = TransactionModel(
        user_idpk=user.id,
        manager_id=manager_id,
        type=TransactionType.WITHDRAW_REQUEST.value,
        method="manual",
        plan="manual",
        amount=amount,
        currency="RUB",
        credits=0,
        status=(
            TransactionStatus.ASSIGNED.value
            if manager_id
            else TransactionStatus.PENDING.value
        ),
        payload="withdraw_request",
        details=details,
    )
    try:
        session.add(transaction)
        await session.flush()
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось сохранить заявку на вывод: %s", err)
        try:
            stmt = (
                update(UserModel)
                .where(UserModel.user_id == user.user_id)
                .values(balance=UserModel.balance + amount)
            )
            await session.execute(stmt)
            await session.commit()
            await UserRD.delete(redis, user.user_id)
        except Exception as refund_err:
            await session.rollback()
            logger.warning(
                "Не удалось вернуть баланс при ошибке заявки: %s",
                refund_err,
            )
        await message.answer(
            "Не удалось создать заявку на вывод. Средства возвращены.",
            reply_markup=await ik_back_earn(),
        )
        await state.clear()
        return

    if manager_id:
        sent = await _notify_manager(
            bot=message.bot,
            manager_id=manager_id,
            transaction_id=transaction.id,
            user=user,
            amount=amount,
            details=details,
        )
        if not sent:
            await _unassign_manager(session, transaction.id)
            await message.answer(
                "Заявка принята, но менеджер недоступен. Мы свяжемся позже.",
                reply_markup=await ik_back_earn(),
            )
            await state.clear()
            return

    await message.answer(
        "Заявка на вывод принята. Мы свяжемся с вами в ближайшее время.",
        reply_markup=await ik_back_earn(),
    )
    await state.clear()


async def _select_manager_id(session: AsyncSession) -> int | None:
    manager_ids = se.withdraw.manager_ids
    if not manager_ids:
        logger.warning("Не настроены менеджеры для вывода средств")
        return None

    loads = await get_manager_loads(session, manager_ids)
    return pick_manager_id(manager_ids, loads)


async def _notify_manager(
    *,
    bot: Bot,
    manager_id: int,
    transaction_id: int,
    user: UserRD,
    amount: int,
    details: str,
) -> bool:
    username = f"@{user.username}" if user.username else "без username"
    text = (
        "Новая заявка на вывод средств\n"
        f"Заявка: #{transaction_id}\n"
        f"Пользователь: {user.name} ({username})\n"
        f"ID пользователя: {user.user_id}\n"
        f"Сумма: {format_rub(amount)} руб.\n"
        f"Реквизиты: {details}"
    )
    try:
        await bot.send_message(
            manager_id,
            text,
            reply_markup=await ik_withdraw_manager(transaction_id),
        )
        return True
    except Exception as err:
        logger.warning("Не удалось отправить заявку менеджеру: %s", err)
        return False


async def _unassign_manager(session: AsyncSession, transaction_id: int) -> None:
    stmt = (
        update(TransactionModel)
        .where(TransactionModel.id == transaction_id)
        .values(manager_id=None, status=TransactionStatus.PENDING.value)
    )
    try:
        await session.execute(stmt)
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось снять назначение менеджера: %s", err)
