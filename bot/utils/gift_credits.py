from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from bot.db.func import expire_gift_credits

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

logger = logging.getLogger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

# Размер подарка при ре-активации «нулевых» пользователей.
REACTIVATION_GIFT_CREDITS = 3


def gift_expiry_end_of_day() -> datetime:
    """Момент сгорания подарка — конец текущего дня по Москве, в naive UTC.

    Подарок действует «до конца дня»: если начислить вечером, у пользователя
    может остаться сильно меньше суток. Храним в naive UTC, как и остальные
    отметки времени в проекте (см. ``admin_stats``)."""
    now_msk = datetime.now(MOSCOW_TZ)
    end_of_day_msk = now_msk.replace(hour=23, minute=59, second=59, microsecond=0)
    return end_of_day_msk.astimezone(UTC).replace(tzinfo=None)


async def run_gift_expiry(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    """Сжечь просроченные подарочные кредиты. Запускается планировщиком."""
    try:
        async with sessionmaker() as session:
            burned = await expire_gift_credits(session=session, redis=redis)
        if burned:
            logger.info("Сгорели подарочные кредиты у %s пользователей", burned)
    except Exception:
        logger.exception("Ошибка при сгорании подарочных кредитов")
