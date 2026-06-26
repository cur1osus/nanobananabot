from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from sqlalchemy import select

from bot.db.enum import GenerationTaskStatus
from bot.db.func import charge_user_credits, refund_user_credits
from bot.db.models import GenerationTaskModel, UserModel
from bot.db.redis.user_model import UserRD

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# Замок держится не дольше, чем самая долгая генерация (видео ~300с + запас),
# чтобы при падении процесса он гарантированно протух и не заблокировал юзера.
LOCK_TTL_SECONDS = 900


class GenerationBusy(Exception):
    """У пользователя уже идёт генерация — параллельный запуск запрещён."""


class CreditsExhausted(Exception):
    """Не хватило кредитов на момент атомарного списания."""

    def __init__(self, required: int) -> None:
        super().__init__(f"Недостаточно кредитов: нужно {required}")
        self.required = required


def _lock_key(user_id: int) -> str:
    return f"genlock:{user_id}"


@asynccontextmanager
async def reserve_generation(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    cost: int,
    kind: str,
) -> AsyncIterator[GenerationTaskModel]:
    """Зарезервировать кредиты под одну генерацию.

    Последовательность гарантирует, что пользователь не сможет обойти оплату
    параллельными запросами и что деньги не «потеряются» при сбое:

    1. Берётся персональный Redis-замок (один запуск на пользователя).
    2. Кредиты списываются атомарно (``WHERE credits >= cost``) ДО генерации.
    3. Создаётся запись ``GenerationTaskModel`` в статусе ``processing``.
    4. Тело ``with`` выполняет генерацию и доставку результата.
    5. При нормальном выходе запись помечается ``success``.
    6. При любой ошибке кредиты возвращаются, запись — ``refunded``.

    Бросает :class:`GenerationBusy`, если генерация уже идёт, и
    :class:`CreditsExhausted`, если кредитов не хватило.
    """
    acquired = await redis.set(
        _lock_key(user.user_id), b"1", nx=True, ex=LOCK_TTL_SECONDS
    )
    if not acquired:
        raise GenerationBusy

    task: GenerationTaskModel | None = None
    try:
        charged = await charge_user_credits(
            session=session,
            redis=redis,
            user=user,
            amount=cost,
        )
        if not charged:
            raise CreditsExhausted(cost)

        task = GenerationTaskModel(
            user_idpk=user.id,
            kind=kind,
            credits_cost=cost,
            status=GenerationTaskStatus.PROCESSING.value,
        )
        session.add(task)
        await session.commit()

        yield task

        task.status = GenerationTaskStatus.SUCCESS.value
        await session.commit()
    except BaseException:
        if task is not None:
            await _safe_refund(
                session=session,
                redis=redis,
                user=user,
                task=task,
                cost=cost,
            )
        raise
    finally:
        await redis.delete(_lock_key(user.user_id))


async def _safe_refund(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    task: GenerationTaskModel,
    cost: int,
) -> None:
    try:
        await refund_user_credits(
            session=session,
            redis=redis,
            user=user,
            amount=cost,
        )
        task.status = GenerationTaskStatus.REFUNDED.value
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception(
            "Не удалось вернуть кредиты после ошибки генерации: user_id=%s cost=%s",
            user.user_id,
            cost,
        )


async def recover_orphan_generations(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    """Вернуть кредиты по генерациям, зависшим в ``processing`` после рестарта.

    Генерации фото/видео выполняются синхронно в процессе бота, поэтому любая
    запись ``processing`` на старте — это прерванная падением/деплоем задача,
    деньги за которую нужно вернуть пользователю.
    """
    async with sessionmaker() as session:
        stmt = select(GenerationTaskModel).where(
            GenerationTaskModel.status == GenerationTaskStatus.PROCESSING.value
        )
        orphans = (await session.scalars(stmt)).all()
        if not orphans:
            return

        refunded = 0
        for task in orphans:
            user_db = await session.scalar(
                select(UserModel).where(UserModel.id == task.user_idpk)
            )
            if user_db and task.credits_cost > 0:
                await refund_user_credits(
                    session=session,
                    redis=redis,
                    user=UserRD.from_orm(user_db),
                    amount=task.credits_cost,
                )
            task.status = GenerationTaskStatus.REFUNDED.value
            refunded += 1
        await session.commit()
        logger.info("Возвращены кредиты по %s прерванным генерациям", refunded)
