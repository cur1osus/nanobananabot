from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import aiohttp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import TransactionStatus, TransactionType
from bot.db.models import TransactionModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.settings import se
from bot.utils.formatting import format_rub
from bot.utils.http_client import create_client_session, resolve_proxy_settings
from bot.utils.payments import CARD_CURRENCY, STARS_CURRENCY

if TYPE_CHECKING:
    from redis.asyncio import Redis

ONLINE_MINUTES: Final[int] = 15
_ALL_TIME_START: Final[datetime] = datetime(2020, 1, 1)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeriodBounds:
    start: datetime
    end: datetime
    prev_start: datetime
    prev_end: datetime


def get_period_bounds(period: str, now: datetime) -> PeriodBounds:
    if period == "all":
        return PeriodBounds(
            start=_ALL_TIME_START,
            end=now,
            prev_start=_ALL_TIME_START,
            prev_end=_ALL_TIME_START,
        )
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
    period_label = "Всё время" if period == "all" else _format_period(bounds.start, bounds.end)

    total_users = await session.scalar(select(func.count(UserModel.id))) or 0
    new_users = await _count_users(session, bounds.start, bounds.end)

    online_users = await UserRD.count_online(redis, threshold_minutes=ONLINE_MINUTES)

    sales_current = await _sum_sales(session, bounds.start, bounds.end)
    withdrawals_current = await _sum_transactions(
        session,
        TransactionType.WITHDRAW_REQUEST.value,
        TransactionStatus.COMPLETED.value,
        bounds.start,
        bounds.end,
    )

    if period == "all":
        card_sales = sales_current.get(CARD_CURRENCY, 0)
        stars_sales = sales_current.get(STARS_CURRENCY, 0)
        return (
            f"📊 Инфо — период: {period_label}\n\n"
            f"Продажи (карта): {format_rub(card_sales)} р.\n"
            f"Продажи (звезды): {stars_sales}\n"
            f"Выводы реферерам: {format_rub(withdrawals_current)} р.\n\n"
            f"Всего пользователей: {total_users}\n"
            f"Онлайн ({ONLINE_MINUTES} мин): {online_users}"
        )

    sales_prev = await _sum_sales(session, bounds.prev_start, bounds.prev_end)
    withdrawals_prev = await _sum_transactions(
        session,
        TransactionType.WITHDRAW_REQUEST.value,
        TransactionStatus.COMPLETED.value,
        bounds.prev_start,
        bounds.prev_end,
    )

    return (
        f"📊 Инфо — период: \n{period_label}\n\n"
        f"Продажи (карта): {_format_sales_by_currency(sales_current, sales_prev, CARD_CURRENCY)}\n"
        f"Продажи (звезды): {_format_sales_by_currency(sales_current, sales_prev, STARS_CURRENCY)}\n"
        f"Выводы реферерам: {format_rub(withdrawals_current)} р. ({_format_delta_rub(withdrawals_current - withdrawals_prev)})\n\n"
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


def _supports_balance_endpoint(*, provider: str, base_url: str) -> bool:
    if provider in ("google", "runware"):
        return False
    return True


async def _fetch_all_gpt_balances() -> str:
    if not _supports_balance_endpoint(
        provider=se.image_backend.provider,
        base_url=se.image_backend.base_url,
    ):
        return "• API: н/д (provider не поддерживает endpoint /balance)"

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
        proxy_settings = resolve_proxy_settings(se.image_backend.proxy_url)
        async with create_client_session(
            timeout=timeout,
            proxy_settings=proxy_settings,
        ) as session:
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


async def fetch_runware_account_text() -> str:
    if se.image_backend.provider != "runware":
        return "Провайдер не Runware — информация об аккаунте недоступна."

    if not se.image_backend.api_key:
        return "API ключ не задан (IMAGE_BACKEND_API_KEY)."

    url = f"{se.image_backend.base_url.rstrip('/')}/tasks"
    payload = [
        {
            "taskType": "accountManagement",
            "taskUUID": str(uuid.uuid4()),
            "operation": "getDetails",
        }
    ]

    try:
        timeout = aiohttp.ClientTimeout(total=8)
        proxy_settings = resolve_proxy_settings(se.image_backend.proxy_url)
        async with create_client_session(timeout=timeout, proxy_settings=proxy_settings) as session:
            async with session.post(
                url,
                headers={
                    "Authorization": f"Bearer {se.image_backend.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.warning(
                        "Runware account API error: status=%s body=%s",
                        response.status,
                        body[:200],
                    )
                    return f"Ошибка Runware API: {response.status}"
                data = await response.json()
    except Exception as err:
        logger.warning("Runware account fetch failed: %s", err)
        return "Не удалось получить данные аккаунта."

    results = data.get("data") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        logger.warning("Runware account unexpected response: %s", data)
        return "Пустой ответ от Runware API."

    info = results[0]
    if not isinstance(info, dict):
        return f"Некорректный ответ: {info}"

    def _get(d: object, *keys: str, default: str = "—") -> str:
        for k in keys:
            if not isinstance(d, dict):
                return default
            d = d.get(k, default)  # type: ignore[assignment]
        return str(d) if d != default else default

    org_name = _get(info, "organization", "name")
    balance_amount = _get(info, "balance", "amount")
    balance_free = _get(info, "balance", "freeAmount")
    balance_currency = _get(info, "balance", "currency", default="$")

    today_credits = _get(info, "usage", "today", "credits")
    today_requests = _get(info, "usage", "today", "requests")
    week_credits = _get(info, "usage", "last7Days", "credits")
    week_requests = _get(info, "usage", "last7Days", "requests")
    month_credits = _get(info, "usage", "last30Days", "credits")
    month_requests = _get(info, "usage", "last30Days", "requests")
    total_credits = _get(info, "usage", "total", "credits")
    total_requests = _get(info, "usage", "total", "requests")

    return (
        f"🏢 <b>Runware аккаунт</b>\n"
        f"Организация: {org_name}\n\n"
        f"💰 <b>Баланс</b>\n"
        f"Основной: {balance_amount} {balance_currency}\n"
        f"Бесплатный: {balance_free} {balance_currency}\n\n"
        f"📈 <b>Использование</b>\n"
        f"Сегодня: {today_credits} cr / {today_requests} запросов\n"
        f"7 дней: {week_credits} cr / {week_requests} запросов\n"
        f"30 дней: {month_credits} cr / {month_requests} запросов\n"
        f"Всего: {total_credits} cr / {total_requests} запросов"
    )
