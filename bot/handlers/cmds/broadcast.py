from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.enum import UserRole
from bot.db.models import UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.states import BroadcastState

router = Router()
logger = logging.getLogger(__name__)

# Telegram допускает ~30 сообщений в секунду на бота при массовой рассылке.
# Небольшая пауза между отправками удерживает нас ниже лимита и снижает
# вероятность TelegramRetryAfter.
_SEND_DELAY = 0.05


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправить всем", callback_data="broadcast:send"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data="broadcast:cancel"
                ),
            ]
        ]
    )


@router.callback_query(MenuAction.filter(F.action == "broadcast"))
async def broadcast_start(
    query: CallbackQuery,
    user: UserRD,
    state: FSMContext,
) -> None:
    await query.answer()
    if user.role != UserRole.ADMIN.value:
        await query.answer("Нет доступа.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        return

    await state.set_state(BroadcastState.waiting_message)
    await query.message.answer(
        "Пришлите сообщение для рассылки — текст, фото, видео, документ, "
        "голосовое или любой другой тип. Оно будет разослано всем пользователям "
        "копией (без отметки «переслано»).\n\n"
        "Для отмены отправьте /cancel."
    )


@router.message(BroadcastState.waiting_message, Command("cancel"))
async def broadcast_cancel_input(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer("Рассылка отменена.")


@router.message(BroadcastState.waiting_message)
async def broadcast_receive(
    message: Message,
    user: UserRD,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if user.role != UserRole.ADMIN.value:
        await state.clear()
        await message.answer("У вас нет прав на выполнение этой команды.")
        return

    total = await session.scalar(select(func.count(UserModel.user_id)))
    await state.update_data(
        broadcast_chat_id=message.chat.id,
        broadcast_message_id=message.message_id,
    )
    await state.set_state(BroadcastState.confirm)
    await message.answer(
        f"Предпросмотр выше 👆\n"
        f"Получателей: {total or 0}.\n\n"
        f"Разослать это сообщение всем пользователям?",
        reply_markup=_confirm_keyboard(),
    )


@router.callback_query(BroadcastState.confirm, F.data == "broadcast:cancel")
async def broadcast_confirm_cancel(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
    await query.answer("Рассылка отменена.")
    if isinstance(query.message, Message):
        await query.message.answer("Рассылка отменена.")


@router.callback_query(BroadcastState.confirm, F.data == "broadcast:send")
async def broadcast_confirm_send(
    query: CallbackQuery,
    user: UserRD,
    state: FSMContext,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    if user.role != UserRole.ADMIN.value:
        await query.answer("Нет доступа к этой операции.", show_alert=True)
        return

    data = await state.get_data()
    from_chat_id = data.get("broadcast_chat_id")
    message_id = data.get("broadcast_message_id")
    await state.clear()

    if not from_chat_id or not message_id:
        await query.answer("Сообщение для рассылки потеряно.", show_alert=True)
        return

    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
    await query.answer("Рассылка запущена.")

    admin_chat_id = query.from_user.id
    asyncio.create_task(
        _run_broadcast(
            bot=bot,
            sessionmaker=sessionmaker,
            from_chat_id=int(from_chat_id),
            message_id=int(message_id),
            admin_chat_id=admin_chat_id,
        )
    )


async def _run_broadcast(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    from_chat_id: int,
    message_id: int,
    admin_chat_id: int,
) -> None:
    """Скопировать сообщение всем пользователям и прислать админу отчёт.

    Запускается фоновой задачей, поэтому открывает собственную сессию БД:
    request-scoped сессия хендлера к моменту выполнения уже закрыта."""
    async with sessionmaker() as session:
        user_ids = list(
            await session.scalars(select(UserModel.user_id).order_by(UserModel.id))
        )

    sent = 0
    blocked = 0
    failed = 0

    for user_id in user_ids:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            sent += 1
        except TelegramRetryAfter as err:
            # Лимит flood control — подождать и повторить один раз.
            await asyncio.sleep(err.retry_after)
            try:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
                sent += 1
            except Exception as retry_err:  # noqa: BLE001
                failed += 1
                logger.warning(
                    "Рассылка: повтор для %s не удался: %s", user_id, retry_err
                )
        except TelegramForbiddenError:
            # Пользователь заблокировал бота или удалил аккаунт.
            blocked += 1
        except Exception as err:  # noqa: BLE001
            failed += 1
            logger.warning("Рассылка: не удалось отправить %s: %s", user_id, err)

        await asyncio.sleep(_SEND_DELAY)

    logger.info(
        "Рассылка завершена: всего=%s, доставлено=%s, заблокировали=%s, ошибок=%s",
        len(user_ids),
        sent,
        blocked,
        failed,
    )

    try:
        await bot.send_message(
            admin_chat_id,
            "Рассылка завершена.\n"
            f"Всего пользователей: {len(user_ids)}\n"
            f"Доставлено: {sent}\n"
            f"Заблокировали бота: {blocked}\n"
            f"Ошибок: {failed}",
        )
    except Exception as err:  # noqa: BLE001
        logger.warning("Не удалось отправить отчёт о рассылке админу: %s", err)
