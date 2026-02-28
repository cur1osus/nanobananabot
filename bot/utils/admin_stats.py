from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import (
    MusicTaskStatus,
    TransactionStatus,
    TransactionType,
    UsageEventType,
)
from bot.db.models import MusicTaskModel, TransactionModel, UsageEventModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.utils.formatting import format_rub
from bot.utils.payments import CARD_CURRENCY, STARS_CURRENCY
from bot.utils.speech_recognition import SpeechRecognitionError, get_vsegpt_balance
from bot.utils.suno_api import SunoAPIError, build_suno_client

if TYPE_CHECKING:
    from redis.asyncio import Redis

ONLINE_MINUTES: Final[int] = 15
MUSIC_TASK_SUCCESS: Final[str] = MusicTaskStatus.SUCCESS.value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeriodBounds:
    start: datetime
    end: datetime
    prev_start: datetime
    prev_end: datetime


def get_period_bounds(period: str, now: datetime) -> PeriodBounds:
    if period == "week":
        delta = timedelta(days=7)
    elif period == "month":
        delta = timedelta(days=30)
    else:
        delta = timedelta(days=1)
    start = now - delta
    prev_start = start - delta
    return PeriodBounds(start=start, end=now, prev_start=prev_start, prev_end=start)


async def build_admin_info_text(
    session: AsyncSession, redis: Redis, period: str
) -> str:
    db_now = await session.scalar(select(func.now()))
    now = (
        db_now
        if isinstance(db_now, datetime)
        else datetime.now(tz=UTC).replace(tzinfo=None)
    )
    bounds = get_period_bounds(period, now)
    period_label = _format_period(bounds.start, bounds.end)

    total_users = await session.scalar(select(func.count(UserModel.id))) or 0
    new_users = await _count_users(session, bounds.start, bounds.end)

    online_users = await UserRD.count_online(redis, threshold_minutes=ONLINE_MINUTES)

    sales_current = await _sum_sales(session, bounds.start, bounds.end)
    sales_prev = await _sum_sales(session, bounds.prev_start, bounds.prev_end)
    withdrawals_current = await _sum_transactions(
        session,
        TransactionType.WITHDRAW_REQUEST.value,
        TransactionStatus.COMPLETED.value,
        bounds.start,
        bounds.end,
    )
    withdrawals_prev = await _sum_transactions(
        session,
        TransactionType.WITHDRAW_REQUEST.value,
        TransactionStatus.COMPLETED.value,
        bounds.prev_start,
        bounds.prev_end,
    )

    songs_current = await _count_music_tasks(session, bounds.start, bounds.end)
    songs_prev = await _count_music_tasks(session, bounds.prev_start, bounds.prev_end)
    ai_texts_current = await _count_events(
        session,
        UsageEventType.AI_TEXT.value,
        bounds.start,
        bounds.end,
    )
    ai_texts_prev = await _count_events(
        session,
        UsageEventType.AI_TEXT.value,
        bounds.prev_start,
        bounds.prev_end,
    )
    manual_texts_current = await _count_events(
        session,
        UsageEventType.MANUAL_TEXT.value,
        bounds.start,
        bounds.end,
    )
    manual_texts_prev = await _count_events(
        session,
        UsageEventType.MANUAL_TEXT.value,
        bounds.prev_start,
        bounds.prev_end,
    )
    instrumental_current = await _count_events(
        session,
        UsageEventType.INSTRUMENTAL.value,
        bounds.start,
        bounds.end,
    )
    instrumental_prev = await _count_events(
        session,
        UsageEventType.INSTRUMENTAL.value,
        bounds.prev_start,
        bounds.prev_end,
    )
    suno_credits = await _fetch_suno_credits()
    vsegpt_credits = await _fetch_vsegpt_credits()

    return (
        f"📊 Инфо — период: \n{period_label}\n\n"
        f"Продажи (карта): {_format_sales_by_currency(sales_current, sales_prev, CARD_CURRENCY)}\n"
        f"Продажи (звезды): {_format_sales_by_currency(sales_current, sales_prev, STARS_CURRENCY)}\n"
        f"Выводы реферерам: {format_rub(withdrawals_current)} р. ({_format_delta_rub(withdrawals_current - withdrawals_prev)})\n\n"
        f"Кредиты SunoApi: {suno_credits}\n"
        f"Кредиты VseGpt: {vsegpt_credits}\n\n"
        f"Песни: {songs_current} ({_format_delta(songs_current, songs_prev)})\n"
        f"Сгенерированные тексты: {ai_texts_current} ({_format_delta(ai_texts_current, ai_texts_prev)})\n"
        f"Сгенерированные инструменталы: {instrumental_current} ({_format_delta(instrumental_current, instrumental_prev)})\n\n"
        f"Тексты введены вручную: {manual_texts_current} ({_format_delta(manual_texts_current, manual_texts_prev)})\n\n"
        f"Всего пользователей: {total_users} (+{new_users})\n"
        f"Онлайн ({ONLINE_MINUTES} мин): {online_users}"
    )


async def _count_users(session: AsyncSession, start: datetime, end: datetime) -> int:
    return (
        await session.scalar(
            select(func.count(UserModel.id)).where(
                UserModel.registration_datetime >= start,
                UserModel.registration_datetime < end,
            )
        )
        or 0
    )


async def _count_events(
    session: AsyncSession,
    event_type: str,
    start: datetime,
    end: datetime,
) -> int:
    return (
        await session.scalar(
            select(func.count(UsageEventModel.id)).where(
                UsageEventModel.event_type == event_type,
                UsageEventModel.created_at >= start,
                UsageEventModel.created_at < end,
            )
        )
        or 0
    )


async def _count_music_tasks(
    session: AsyncSession,
    start: datetime,
    end: datetime,
) -> int:
    return (
        await session.scalar(
            select(func.count(MusicTaskModel.id)).where(
                MusicTaskModel.status == MUSIC_TASK_SUCCESS,
                MusicTaskModel.updated_at >= start,
                MusicTaskModel.updated_at < end,
            )
        )
        or 0
    )


async def _sum_sales(
    session: AsyncSession,
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    stmt = (
        select(
            TransactionModel.currency,
            func.coalesce(func.sum(TransactionModel.amount), 0),
        )
        .where(
            TransactionModel.type == TransactionType.TOPUP.value,
            TransactionModel.status == TransactionStatus.SUCCESS.value,
            TransactionModel.created_at >= start,
            TransactionModel.created_at < end,
        )
        .group_by(TransactionModel.currency)
    )
    rows = await session.execute(stmt)
    return {currency: int(total or 0) for currency, total in rows}


def _format_sales_by_currency(
    current: dict[str, int],
    prev: dict[str, int],
    currency: str,
) -> str:
    amount = current.get(currency, 0)
    prev_amount = prev.get(currency, 0)
    delta = amount - prev_amount
    if currency == CARD_CURRENCY:
        return f"{format_rub(amount)} р. ({_format_delta_rub(delta)})"
    return f"{amount} ({_format_delta_int(delta)})"


async def _sum_transactions(
    session: AsyncSession,
    tx_type: str,
    tx_status: str,
    start: datetime,
    end: datetime,
) -> int:
    return (
        await session.scalar(
            select(func.coalesce(func.sum(TransactionModel.amount), 0)).where(
                TransactionModel.type == tx_type,
                TransactionModel.status == tx_status,
                TransactionModel.created_at >= start,
                TransactionModel.created_at < end,
            )
        )
        or 0
    )


def _format_delta(current: int, previous: int) -> str:
    diff = current - previous
    sign = "+" if diff >= 0 else "-"
    return f"{sign}{abs(diff)}"


def _format_period(start: datetime, end: datetime) -> str:
    return f"{start:%d.%m.%Y %H:%M} — {end:%d.%m.%Y %H:%M}"


async def _fetch_suno_credits() -> str:
    try:
        credits = await build_suno_client().get_remaining_credits()
    except SunoAPIError as err:
        logger.warning("Не удалось получить Hit$ Suno: %s", err)
        return "недоступно"
    return f"{credits} (~{credits // 12} песен)"


async def _fetch_vsegpt_credits() -> str:
    try:
        credits = await get_vsegpt_balance()
    except SpeechRecognitionError as err:
        logger.warning("Не удалось получить кредиты VseGpt: %s", err)
        return "недоступно"
    return f"{credits:.2f}"


def _format_delta_int(value: int) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value)}"


def _format_delta_rub(amount: int) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{format_rub(abs(amount))} р."
