from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from bot.db.enum import GenerationTaskStatus
from bot.db.func import charge_user_credits, refund_user_credits
from bot.db.models import GenerationTaskModel, UserModel
from bot.db.redis.user_model import UserRD

if TYPE_CHECKING:
    from aiogram import Bot
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (
    GenerationTaskStatus.QUEUED.value,
    GenerationTaskStatus.PROCESSING.value,
)

# Асинхронная «студия»: пользователь может держать в работе до N генераций
# одновременно (queued+processing). Глобальную параллельность воркера держим
# выше (см. background_tasks.MAX_CONCURRENT_GENERATIONS), чтобы один пользователь
# не занимал все слоты.
MAX_ACTIVE_GENERATIONS_PER_USER = 3


class GenerationBusy(Exception):
    """У пользователя уже максимум активных генераций — очередь заполнена."""


class CreditsExhausted(Exception):
    """Не хватило кредитов на момент атомарного списания."""

    def __init__(self, required: int) -> None:
        super().__init__(f"Недостаточно кредитов: нужно {required}")
        self.required = required


async def enqueue_generation(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    kind: str,
    cost: int,
    chat_id: int,
    status_message_id: int | None,
    params: dict[str, Any],
) -> GenerationTaskModel:
    """Поставить генерацию в очередь с гарантией оплаты и переживанием рестарта.

    1. Проверяем, что у пользователя меньше ``MAX_ACTIVE_GENERATIONS_PER_USER``
       активных генераций (``queued``/``processing``).
    2. Атомарно списываем кредиты (``WHERE credits >= cost``) ДО постановки.
    3. Создаём запись ``GenerationTaskModel`` в статусе ``queued`` со всеми
       параметрами, нужными воркеру для выполнения (в т.ч. после рестарта).

    Бросает :class:`GenerationBusy`, если лимит активных генераций исчерпан, и
    :class:`CreditsExhausted`, если кредитов не хватило. Подсчёт активных
    безопасен без отдельного замка: апдейты одного пользователя сериализуются
    per-user изоляцией событий aiogram.
    """
    active_count = await session.scalar(
        select(func.count(GenerationTaskModel.id)).where(
            GenerationTaskModel.user_idpk == user.id,
            GenerationTaskModel.status.in_(_ACTIVE_STATUSES),
        )
    )
    if (active_count or 0) >= MAX_ACTIVE_GENERATIONS_PER_USER:
        raise GenerationBusy

    # Задачу добавляем в сессию ДО списания: единственный commit внутри
    # charge_user_credits персистит и списание, и вставку задачи в одной
    # транзакции. Если вставка падает (или кредитов не хватило) — откатывается
    # и списание, поэтому кредиты не могут «сгореть» без созданной задачи.
    task = GenerationTaskModel(
        user_idpk=user.id,
        kind=kind,
        credits_cost=cost,
        status=GenerationTaskStatus.QUEUED.value,
        chat_id=chat_id,
        status_message_id=status_message_id,
        params=json.dumps(params, ensure_ascii=False),
    )
    session.add(task)

    charged = await charge_user_credits(
        session=session,
        redis=redis,
        user=user,
        amount=cost,
    )
    if not charged:
        raise CreditsExhausted(cost)

    return task


async def refund_generation(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    task: GenerationTaskModel,
    cost: int,
) -> None:
    """Вернуть кредиты по задаче и пометить её ``refunded`` (idempotent на статусе)."""
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
    bot: Bot | None = None,
) -> None:
    """Восстановить генерации, зависшие в ``processing`` после рестарта.

    - CivitAI с сохранённым ``provider_task_id`` возвращаем в очередь
      (``queued``): воркфлоу живёт на стороне провайдера, воркер его доопросит
      и доставит результат без повторного списания.
    - Остальные (Runware/видео — без возобновляемого id) считаем потерянными:
      возвращаем кредиты и уведомляем пользователя.

    Задачи в статусе ``queued`` трогать не нужно — воркер подхватит их сам.
    """
    notify: list[int] = []
    async with sessionmaker() as session:
        stmt = select(GenerationTaskModel).where(
            GenerationTaskModel.status == GenerationTaskStatus.PROCESSING.value
        )
        orphans = (await session.scalars(stmt)).all()
        if not orphans:
            return

        resumed = 0
        refunded = 0
        for task in orphans:
            if task.provider_task_id:
                task.status = GenerationTaskStatus.QUEUED.value
                resumed += 1
                continue

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
            if task.chat_id:
                notify.append(task.chat_id)
        await session.commit()
        logger.info(
            "Восстановление генераций: возобновлено %s, возвращено кредитов по %s",
            resumed,
            refunded,
        )

    if bot is not None:
        for chat_id in notify:
            try:
                await bot.send_message(
                    chat_id,
                    "⚠️ Генерация была прервана перезапуском сервиса. "
                    "Кредиты возвращены — попробуйте запустить заново.",
                )
            except Exception:
                logger.warning("Не удалось уведомить чат %s о возврате", chat_id)
