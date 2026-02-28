from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from aiogram.types import User
from sqlalchemy import func, select, update
from sqlalchemy.sql.operators import eq, ne

from .models import UserModel
from .redis.user_model import UserRD

if TYPE_CHECKING:
    from redis.asyncio.client import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _create_user(*, user: User, session: AsyncSession) -> UserModel:
    if user.username:
        stmt = select(UserModel).where(
            eq(UserModel.username, user.username), ne(UserModel.user_id, user.id)
        )
        another_user: UserModel | None = await session.scalar(stmt)

        if another_user:
            stmt = (
                update(UserModel)
                .where(eq(UserModel.user_id, another_user.user_id))
                .values(username=None)
            )
            await session.execute(stmt)

    stmt = select(UserModel).where(eq(UserModel.user_id, user.id))
    user_model: UserModel | None = await session.scalar(stmt)

    if not user_model:
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        user_model = UserModel(
            user_id=user.id,
            username=user.username,
            name=user.first_name,
            registration_datetime=now,
            last_active=now,
        )
        session.add(user_model)

    else:
        user_model.username = user.username
        user_model.name = user.first_name

    return cast(UserModel, user_model)


async def _get_user_model(
    *,
    db_pool: async_sessionmaker[AsyncSession],
    redis: Redis,
    user: User,
) -> UserRD:
    user_model = await UserRD.get(redis, user.id)

    if user_model:
        return user_model

    async with db_pool() as session:
        async with session.begin():
            user_model: UserModel = await _create_user(
                user=user,
                session=session,
            )

    user_model: UserRD = UserRD.from_orm(cast(UserModel, user_model))
    await cast(UserRD, user_model).save(redis)

    return cast(UserRD, user_model)


async def charge_user_credits(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    amount: int,
) -> bool:
    if amount <= 0:
        return True

    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, user.user_id), UserModel.credits >= amount)
        .values(credits=UserModel.credits - amount)
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        await session.rollback()
        return False

    await session.commit()
    await user.delete(redis, user.user_id)
    return True


async def refund_user_credits(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    amount: int,
) -> None:
    if amount <= 0:
        return

    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, user.user_id))
        .values(credits=UserModel.credits + amount)
    )
    await session.execute(stmt)
    await session.commit()
    await user.delete(redis, user.user_id)


async def add_user_credits(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    amount: int,
) -> None:
    if amount <= 0:
        return

    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, user.user_id))
        .values(credits=UserModel.credits + amount)
    )
    await session.execute(stmt)
    await session.commit()
    await user.delete(redis, user.user_id)


async def deduct_user_credits(
    *,
    session: AsyncSession,
    redis: Redis,
    user_id: int,
    amount: int,
) -> None:
    if amount <= 0:
        return

    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, user_id))
        .values(credits=func.greatest(UserModel.credits - amount, 0))
    )
    await session.execute(stmt)
    await session.commit()
    await UserRD.delete(redis, user_id)


async def add_referral_balance(
    *,
    session: AsyncSession,
    redis: Redis,
    referrer_id: int,
    amount: int,
) -> bool:
    if amount <= 0:
        return False

    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, referrer_id))
        .values(balance=UserModel.balance + amount)
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        await session.rollback()
        return False

    await session.commit()
    await UserRD.delete(redis, referrer_id)
    return True


async def withdraw_user_balance(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    amount: int,
) -> bool:
    if amount <= 0:
        return False

    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, user.user_id), UserModel.balance >= amount)
        .values(balance=UserModel.balance - amount)
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        await session.rollback()
        return False

    await session.commit()
    await user.delete(redis, user.user_id)
    return True
