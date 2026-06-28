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
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.enum import UserRole
from bot.db.func import grant_gift_credits
from bot.db.models import UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.states import BroadcastState
from bot.utils.background_task_helpers import spawn_background_task
from bot.utils.gift_credits import (
    REACTIVATION_GIFT_CREDITS,
    gift_expiry_end_of_day,
)

router = Router()
logger = logging.getLogger(__name__)

# Telegram допускает ~30 сообщений в секунду на бота при массовой рассылке.
# Небольшая пауза между отправками удерживает нас ниже лимита и снижает
# вероятность TelegramRetryAfter.
_SEND_DELAY = 0.05

_GIFT_MESSAGE = (
    "🎁 У тебя закончились кредиты — держи <b>+{amount}</b> в подарок!\n\n"
    "⏳ Подарок действует только сегодня, до конца дня: завтра неизрасходованные "
    "кредиты сгорят.\n\n"
    "Жми «✨ Генерация изображения» или «🖌 Редактирование фото» в меню "
    "и продолжай творить — /start"
)


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
    spawn_background_task(
        _run_broadcast(
            bot=bot,
            sessionmaker=sessionmaker,
            from_chat_id=int(from_chat_id),
            message_id=int(message_id),
            admin_chat_id=admin_chat_id,
        ),
        name="broadcast",
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
            except Exception as retry_err:
                failed += 1
                logger.warning(
                    "Рассылка: повтор для %s не удался: %s", user_id, retry_err
                )
        except TelegramForbiddenError:
            # Пользователь заблокировал бота или удалил аккаунт.
            blocked += 1
        except Exception as err:
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
    except Exception as err:
        logger.warning("Не удалось отправить отчёт о рассылке админу: %s", err)


def _gift_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Начислить и разослать",
                    callback_data="gift_zero:send",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data="gift_zero:cancel"
                ),
            ]
        ]
    )


@router.callback_query(MenuAction.filter(F.action == "gift_zero"))
async def gift_zero_start(
    query: CallbackQuery,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await query.answer()
    if user.role != UserRole.ADMIN.value:
        await query.answer("Нет доступа.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        return

    total = await session.scalar(
        select(func.count(UserModel.user_id)).where(UserModel.credits == 0)
    )
    if not total:
        await query.message.answer("Пользователей с нулевым балансом нет.")
        return

    await query.message.answer(
        f"Ре-активация «нулевых».\n\n"
        f"Пользователей с 0 кредитов: {total}.\n"
        f"Каждому будет начислено +{REACTIVATION_GIFT_CREDITS} кредитов со "
        f"сгоранием в конце сегодняшнего дня, и отправлено уведомление.\n\n"
        f"Запустить?",
        reply_markup=_gift_confirm_keyboard(),
    )


@router.callback_query(F.data == "gift_zero:cancel")
async def gift_zero_cancel(query: CallbackQuery, user: UserRD) -> None:
    if user.role != UserRole.ADMIN.value:
        await query.answer("Нет доступа.", show_alert=True)
        return
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
    await query.answer("Отменено.")
    if isinstance(query.message, Message):
        await query.message.answer("Ре-активация отменена.")


@router.callback_query(F.data == "gift_zero:send")
async def gift_zero_send(
    query: CallbackQuery,
    user: UserRD,
    bot: Bot,
    redis: Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    if user.role != UserRole.ADMIN.value:
        await query.answer("Нет доступа к этой операции.", show_alert=True)
        return

    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
    await query.answer("Ре-активация запущена.")

    admin_chat_id = query.from_user.id
    spawn_background_task(
        _run_gift_zero(
            bot=bot,
            redis=redis,
            sessionmaker=sessionmaker,
            admin_chat_id=admin_chat_id,
        ),
        name="gift_zero",
    )


async def _run_gift_zero(
    *,
    bot: Bot,
    redis: Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
    admin_chat_id: int,
) -> None:
    """Начислить подарок всем «нулевым» и уведомить их.

    Кредиты начисляются ДО отправки сообщения: даже если пользователь
    заблокировал бота, подарок останется на балансе и сгорит штатно."""
    async with sessionmaker() as session:
        user_ids = list(
            await session.scalars(
                select(UserModel.user_id)
                .where(UserModel.credits == 0)
                .order_by(UserModel.id)
            )
        )

    expires_at = gift_expiry_end_of_day()
    granted = 0
    sent = 0
    blocked = 0
    failed = 0
    text = _GIFT_MESSAGE.format(amount=REACTIVATION_GIFT_CREDITS)

    for user_id in user_ids:
        try:
            async with sessionmaker() as session:
                await grant_gift_credits(
                    session=session,
                    redis=redis,
                    user_id=user_id,
                    amount=REACTIVATION_GIFT_CREDITS,
                    expires_at=expires_at,
                )
            granted += 1
        except Exception as err:
            failed += 1
            logger.warning("Подарок: не удалось начислить %s: %s", user_id, err)
            continue

        try:
            await bot.send_message(user_id, text)
            sent += 1
        except TelegramRetryAfter as err:
            await asyncio.sleep(err.retry_after)
            try:
                await bot.send_message(user_id, text)
                sent += 1
            except Exception as retry_err:
                failed += 1
                logger.warning(
                    "Подарок: повтор уведомления для %s не удался: %s",
                    user_id,
                    retry_err,
                )
        except TelegramForbiddenError:
            blocked += 1
        except Exception as err:
            failed += 1
            logger.warning("Подарок: не удалось уведомить %s: %s", user_id, err)

        await asyncio.sleep(_SEND_DELAY)

    logger.info(
        "Ре-активация завершена: цель=%s, начислено=%s, уведомлено=%s, "
        "заблокировали=%s, ошибок=%s",
        len(user_ids),
        granted,
        sent,
        blocked,
        failed,
    )

    try:
        await bot.send_message(
            admin_chat_id,
            "Ре-активация завершена.\n"
            f"Целевых (0 кредитов): {len(user_ids)}\n"
            f"Начислено подарков: {granted}\n"
            f"Уведомлено: {sent}\n"
            f"Заблокировали бота: {blocked}\n"
            f"Ошибок: {failed}",
        )
    except Exception as err:
        logger.warning("Не удалось отправить отчёт о ре-активации админу: %s", err)
