from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import aiohttp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import TransactionStatus, TransactionType
from bot.db.models import TransactionModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.utils.formatting import format_rub
from bot.utils.payments import CARD_CURRENCY, STARS_CURRENCY
from bot.settings import se

if TYPE_CHECKING:
    from redis.asyncio import Redis

ONLINE_MINUTES: Final[int] = 15

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

    gpt_balances = await _fetch_all_gpt_balances()

    return (
        f"📊 Инфо — период: \n{period_label}\n\n"
        f"Продажи (карта): {_format_sales_by_currency(sales_current, sales_prev, CARD_CURRENCY)}\n"
        f"Продажи (звезды): {_format_sales_by_currency(sales_current, sales_prev, STARS_CURRENCY)}\n"
        f"Выводы реферерам: {format_rub(withdrawals_current)} р. ({_format_delta_rub(withdrawals_current - withdrawals_prev)})\n\n"
        f"Баланс GPT:\n{gpt_balances}\n\n"
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


async def _fetch_all_gpt_balances() -> str:
    result = await _fetch_balance_by_endpoint(
        label="API",
        api_key=se.image_backend.api_key,
        base_url=se.image_backend.base_url,
    )
    return f"• {result}"


async def _fetch_balance_by_endpoint(*, label: str, api_key: str, base_url: str) -> str:
    if not api_key:
        return f"{label}: ключ не задан"

    url = f"{base_url.rstrip('/')}/balance"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.warning(
                        "Не удалось получить баланс %s: %s %s",
                        label,
                        response.status,
                        text[:160],
                    )
                    return f"{label}: недоступно"
                data = await response.json()
    except Exception as err:
        logger.warning("Не удалось получить баланс %s: %s", label, err)
        return f"{label}: недоступно"

    credits_data = data.get("data", {})
    credits = credits_data.get("credits")
    if credits is None:
        return f"{label}: недоступно"

    try:
        return f"{label}: {float(credits):.2f}"
    except (TypeError, ValueError):
        return f"{label}: {credits}"


def _format_delta_int(value: int) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value)}"


def _format_delta_rub(amount: int) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{format_rub(abs(amount))} р."
