from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from bot.db.models import UserModel
from bot.db.redis.user_model import UserRD


def parse_referrer_id(payload: str) -> int | None:
    if not payload.startswith("ref_"):
        return None
    raw_id = payload.removeprefix("ref_").strip()
    if not raw_id.isdigit():
        return None
    return int(raw_id)


async def apply_referral(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    payload: str,
) -> bool:
    if user.referrer_id:
        return False
    referrer_id = parse_referrer_id(payload)
    if referrer_id is None or referrer_id == user.user_id:
        return False

    stmt = select(UserModel).where(UserModel.user_id == user.user_id)
    user_db = await session.scalar(stmt)
    if not user_db or user_db.referrer_id:
        return False

    stmt = select(UserModel).where(UserModel.user_id == referrer_id)
    referrer_db = await session.scalar(stmt)
    if not referrer_db:
        return False

    user_db.referrer_id = referrer_id
    await session.commit()

    await UserRD.delete(redis, user_db.user_id)
    return True
