from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import UsageEventModel, UserModel

logger = logging.getLogger(__name__)


async def record_usage_event(
    *,
    session: AsyncSession,
    user_idpk: int,
    event_type: str,
) -> None:
    event = UsageEventModel(user_idpk=user_idpk, event_type=event_type)
    try:
        session.add(event)
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось сохранить событие использования: %s", err)


async def record_usage_event_by_user_id(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: int,
    event_type: str,
) -> None:
    async with sessionmaker() as session:
        user_db = await session.scalar(
            select(UserModel).where(UserModel.user_id == user_id)
        )
        if not user_db:
            logger.warning(
                "Не удалось сохранить событие: пользователь %s не найден",
                user_id,
            )
            return
        event = UsageEventModel(user_idpk=user_db.id, event_type=event_type)
        try:
            session.add(event)
            await session.commit()
        except Exception as err:
            await session.rollback()
            logger.warning("Не удалось сохранить событие использования: %s", err)
