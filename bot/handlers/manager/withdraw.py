from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import TransactionStatus, TransactionType
from bot.db.models import TransactionModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import WithdrawAction
from bot.keyboards.inline import ik_withdraw_cancel, ik_withdraw_manager
from bot.keyboards.reply import CANCEL_BUTTON_TEXT, rk_cancel
from bot.settings import se
from bot.states import ManagerWithdrawState
from bot.utils.formatting import format_rub

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(WithdrawAction.filter(F.action == "done"))
async def withdraw_done(
    query: CallbackQuery,
    callback_data: WithdrawAction,
    session: AsyncSession,
) -> None:
    manager_ids = se.withdraw.manager_ids
    if query.from_user.id not in manager_ids:
        await query.answer("Нет доступа к этой операции.", show_alert=True)
        return

    transaction = await session.scalar(
        select(TransactionModel).where(
            TransactionModel.id == callback_data.transaction_id
        )
    )
    if not transaction or transaction.type != TransactionType.WITHDRAW_REQUEST.value:
        await query.answer("Заявка не найдена.", show_alert=True)
        return

    if transaction.status == TransactionStatus.COMPLETED.value:
        await query.answer("Заявка уже завершена.", show_alert=True)
        return
    if transaction.status == TransactionStatus.FAILED.value:
        await query.answer("Заявка уже отмечена как ошибка.", show_alert=True)
        return

    if transaction.manager_id and transaction.manager_id != query.from_user.id:
        await query.answer(
            "Заявка закреплена за другим менеджером.",
            show_alert=True,
        )
        return

    transaction.status = TransactionStatus.COMPLETED.value
    transaction.manager_id = query.from_user.id
    try:
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось завершить заявку на вывод: %s", err)
        await query.answer("Не удалось завершить заявку. Попробуйте позже.")
        return

    user_db = await session.scalar(
        select(UserModel).where(UserModel.id == transaction.user_idpk)
    )
    if user_db:
        try:
            await query.bot.send_message(
                user_db.user_id,
                "Ваша заявка на вывод средств обработана. Спасибо!",
            )
        except Exception as err:
            logger.warning("Не удалось уведомить пользователя о выводе: %s", err)

    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception as err:
        logger.warning("Не удалось обновить сообщение менеджера: %s", err)

    await query.answer("Заявка отмечена как выполненная.")


@router.callback_query(WithdrawAction.filter(F.action == "error"))
async def withdraw_error_request(
    query: CallbackQuery,
    callback_data: WithdrawAction,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    manager_ids = se.withdraw.manager_ids
    if query.from_user.id not in manager_ids:
        await query.answer("Нет доступа к этой операции.", show_alert=True)
        return

    transaction = await session.scalar(
        select(TransactionModel).where(
            TransactionModel.id == callback_data.transaction_id
        )
    )
    if not transaction or transaction.type != TransactionType.WITHDRAW_REQUEST.value:
        await query.answer("Заявка не найдена.", show_alert=True)
        return

    if transaction.status == TransactionStatus.COMPLETED.value:
        await query.answer("Заявка уже завершена.", show_alert=True)
        return

    if transaction.status == TransactionStatus.FAILED.value:
        await query.answer("Заявка уже отмечена как ошибка.", show_alert=True)
        return

    if transaction.manager_id and transaction.manager_id != query.from_user.id:
        await query.answer(
            "Заявка закреплена за другим менеджером.",
            show_alert=True,
        )
        return

    if transaction.manager_id != query.from_user.id:
        transaction.manager_id = query.from_user.id
        transaction.status = TransactionStatus.ASSIGNED.value
        try:
            await session.commit()
        except Exception as err:
            await session.rollback()
            logger.warning("Не удалось закрепить заявку за менеджером: %s", err)
            await query.answer("Не удалось обработать заявку. Попробуйте позже.")
            return

    await state.set_state(ManagerWithdrawState.error_reason)
    await state.update_data(
        transaction_id=transaction.id,
        manager_message_id=query.message.message_id if query.message else None,
        manager_chat_id=query.message.chat.id if query.message else None,
    )
    if query.message:
        try:
            await query.message.edit_reply_markup(
                reply_markup=await ik_withdraw_cancel(transaction.id)
            )
        except Exception as err:
            logger.warning("Не удалось обновить клавиатуру менеджера: %s", err)
    await query.message.answer(
        f"Опишите причину ошибки для заявки #{transaction.id}:",
        reply_markup=await rk_cancel(),
    )
    await query.answer()


@router.callback_query(WithdrawAction.filter(F.action == "cancel"))
async def withdraw_error_cancel(
    query: CallbackQuery,
    callback_data: WithdrawAction,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    manager_ids = se.withdraw.manager_ids
    if query.from_user.id not in manager_ids:
        await query.answer("Нет доступа к этой операции.", show_alert=True)
        return

    transaction = await session.scalar(
        select(TransactionModel).where(
            TransactionModel.id == callback_data.transaction_id
        )
    )
    if not transaction or transaction.type != TransactionType.WITHDRAW_REQUEST.value:
        await query.answer("Заявка не найдена.", show_alert=True)
        return

    if transaction.status in {
        TransactionStatus.COMPLETED.value,
        TransactionStatus.FAILED.value,
    }:
        await query.answer("Заявка уже завершена.", show_alert=True)
        return

    await state.clear()
    if query.message:
        try:
            await query.message.edit_reply_markup(
                reply_markup=await ik_withdraw_manager(transaction.id)
            )
        except Exception as err:
            logger.warning("Не удалось восстановить клавиатуру: %s", err)

    await query.message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
    await query.answer()


@router.message(ManagerWithdrawState.error_reason)
async def withdraw_error_reason(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    redis: Redis,
) -> None:
    manager_ids = se.withdraw.manager_ids
    if message.from_user and message.from_user.id not in manager_ids:
        await message.answer("Нет доступа к этой операции.")
        await state.clear()
        return

    data = await state.get_data()
    transaction_id = data.get("transaction_id")
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("Причина не должна быть пустой.")
        return

    if reason == CANCEL_BUTTON_TEXT:
        manager_chat_id = data.get("manager_chat_id")
        manager_message_id = data.get("manager_message_id")
        if manager_chat_id and manager_message_id and transaction_id:
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=manager_chat_id,
                    message_id=manager_message_id,
                    reply_markup=await ik_withdraw_manager(int(transaction_id)),
                )
            except Exception as err:
                logger.warning("Не удалось восстановить клавиатуру: %s", err)
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        return

    if not transaction_id:
        await state.clear()
        await message.answer(
            "Не удалось определить заявку. Попробуйте снова.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    transaction = await session.scalar(
        select(TransactionModel).where(TransactionModel.id == transaction_id)
    )
    if not transaction or transaction.type != TransactionType.WITHDRAW_REQUEST.value:
        await state.clear()
        await message.answer(
            "Заявка не найдена.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if transaction.status in {
        TransactionStatus.COMPLETED.value,
        TransactionStatus.FAILED.value,
    }:
        await state.clear()
        await message.answer(
            "Эта заявка уже завершена.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if transaction.manager_id and transaction.manager_id != message.from_user.id:
        await state.clear()
        await message.answer(
            "Заявка закреплена за другим менеджером.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    user_db = await session.scalar(
        select(UserModel).where(UserModel.id == transaction.user_idpk)
    )
    if not user_db:
        logger.warning(
            "Не удалось найти пользователя для возврата по заявке %s",
            transaction_id,
        )
    elif transaction.amount > 0:
        user_db.balance += transaction.amount

    transaction.status = TransactionStatus.FAILED.value
    transaction.manager_id = message.from_user.id
    transaction.details = _append_error_details(transaction.details, reason)
    try:
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось сохранить ошибку по заявке: %s", err)
        await message.answer(
            "Не удалось сохранить ошибку. Попробуйте позже.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if user_db:
        try:
            await UserRD.delete(redis, user_db.user_id)
        except Exception as err:
            logger.warning("Не удалось сбросить кеш пользователя: %s", err)
        try:
            await message.bot.send_message(
                user_db.user_id,
                "Не удалось обработать вашу заявку на вывод.\n"
                f"Причина: {reason}\n"
                f"Сумма {format_rub(transaction.amount)} руб. возвращена на баланс.",
            )
        except Exception as err:
            logger.warning("Не удалось уведомить пользователя об ошибке: %s", err)

    manager_chat_id = data.get("manager_chat_id")
    manager_message_id = data.get("manager_message_id")
    if manager_chat_id and manager_message_id:
        try:
            await message.bot.edit_message_reply_markup(
                chat_id=manager_chat_id,
                message_id=manager_message_id,
                reply_markup=None,
            )
        except Exception as err:
            logger.warning("Не удалось обновить сообщение менеджера: %s", err)

    await state.clear()
    await message.answer("Ошибка сохранена.", reply_markup=ReplyKeyboardRemove())


def _append_error_details(details: str | None, reason: str) -> str:
    base = (details or "").strip()
    suffix = f"Ошибка: {reason}"
    combined = f"{base}\n{suffix}" if base else suffix
    if len(combined) > 255:
        combined = combined[:252].rstrip() + "..."
    return combined
