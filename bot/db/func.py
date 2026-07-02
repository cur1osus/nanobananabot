from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from aiogram.types import User
from sqlalchemy import CursorResult, and_, case, func, select, update
from sqlalchemy.sql.operators import eq, ne

from .models import UserModel
from .redis.user_model import UserRD

if TYPE_CHECKING:
    from redis.asyncio.client import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def create_user(*, user: User, session: AsyncSession) -> UserModel:
    if user.username:
        another_user: UserModel | None = await session.scalar(
            select(UserModel).where(
                eq(UserModel.username, user.username), ne(UserModel.user_id, user.id)
            )
        )

        if another_user:
            await session.execute(
                update(UserModel)
                .where(eq(UserModel.user_id, another_user.user_id))
                .values(username=None)
            )

    user_model: UserModel | None = await session.scalar(
        select(UserModel).where(eq(UserModel.user_id, user.id))
    )

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

    return user_model


async def get_user_model(
    *,
    db_pool: async_sessionmaker[AsyncSession],
    redis: Redis,
    user: User,
) -> UserRD:
    cached = await UserRD.get(redis, user.id)

    if cached:
        return cached

    async with db_pool() as session:
        async with session.begin():
            user_db = await create_user(user=user, session=session)

    user_rd = UserRD.from_orm(user_db)
    await user_rd.save(redis)

    return user_rd


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
        .values(
            credits=UserModel.credits - amount,
            # Подарок тратится в первую очередь: уменьшаем неизрасходованный
            # остаток подарка вместе с обычным списанием, не уходя в минус.
            gift_credits=func.greatest(UserModel.gift_credits - amount, 0),
        )
    )
    result = await session.execute(stmt)
    if cast(CursorResult, result).rowcount == 0:
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

    # Возврат восстанавливает и «подарочность» кредитов, если окно подарка ещё
    # активно: при списании gift_credits уменьшался вместе с общим балансом, и
    # без этого возвращённые кредиты стали бы бессрочными (подарок «не сгорал»).
    # Восстанавливаем только когда остаток подарка ещё > 0 (частично потраченный
    # активный подарок) — чтобы не пометить подарочными постоянные кредиты; LEAST
    # не даёт gift_credits превысить новый общий баланс.
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, user.user_id))
        .values(
            credits=UserModel.credits + amount,
            gift_credits=case(
                (
                    and_(
                        UserModel.gift_credits > 0,
                        UserModel.gift_expires_at.is_not(None),
                        UserModel.gift_expires_at > now,
                    ),
                    func.least(
                        UserModel.gift_credits + amount,
                        UserModel.credits + amount,
                    ),
                ),
                else_=UserModel.gift_credits,
            ),
        )
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


async def grant_gift_credits(
    *,
    session: AsyncSession,
    redis: Redis,
    user_id: int,
    amount: int,
    expires_at: datetime,
) -> None:
    """Начислить подарочные кредиты со сроком сгорания.

    Кредиты добавляются к общему балансу, а ``gift_credits`` / ``gift_expires_at``
    помечают, какая часть и до какого момента считается подарком. Новый подарок
    перезаписывает срок и суммируется с неизрасходованным остатком прежнего.
    """
    if amount <= 0:
        return

    stmt = (
        update(UserModel)
        .where(eq(UserModel.user_id, user_id))
        .values(
            credits=UserModel.credits + amount,
            gift_credits=UserModel.gift_credits + amount,
            gift_expires_at=expires_at,
        )
    )
    await session.execute(stmt)
    await session.commit()
    await UserRD.delete(redis, user_id)


async def expire_gift_credits(
    *,
    session: AsyncSession,
    redis: Redis,
) -> int:
    """Сжечь неизрасходованные подарочные кредиты с истёкшим сроком.

    Возвращает число затронутых пользователей. У каждого из общего баланса
    вычитается оставшийся подарок (но не ниже нуля), а подарочные поля
    обнуляются. Кэш Redis по затронутым пользователям инвалидируется.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    expired_user_ids = list(
        await session.scalars(
            select(UserModel.user_id).where(
                UserModel.gift_credits > 0,
                UserModel.gift_expires_at.is_not(None),
                UserModel.gift_expires_at <= now,
            )
        )
    )
    if not expired_user_ids:
        return 0

    stmt = (
        update(UserModel)
        .where(
            UserModel.gift_credits > 0,
            UserModel.gift_expires_at.is_not(None),
            UserModel.gift_expires_at <= now,
        )
        .values(
            credits=func.greatest(UserModel.credits - UserModel.gift_credits, 0),
            gift_credits=0,
            gift_expires_at=None,
        )
    )
    await session.execute(stmt)
    await session.commit()

    for user_id in expired_user_ids:
        await UserRD.delete(redis, user_id)
    return len(expired_user_ids)


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
    if cast(CursorResult, result).rowcount == 0:
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
    if cast(CursorResult, result).rowcount == 0:
        await session.rollback()
        return False

    await session.commit()
    await user.delete(redis, user.user_id)
    return True
