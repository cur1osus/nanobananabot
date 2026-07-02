from __future__ import annotations

import enum
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.exc import IntegrityError

from bot.db.models import PromoCodeModel, PromoRedemptionModel, UserModel
from bot.db.redis.user_model import UserRD

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Длину кода ограничиваем размером колонки, чтобы явный ввод не падал на вставке.
MAX_CODE_LENGTH = 64


class PromoResult(enum.Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    ALREADY_USED = "already_used"
    ERROR = "error"


def normalize_code(code: str) -> str:
    """Промокоды регистронезависимы: храним и сравниваем в верхнем регистре."""
    return code.strip().upper()


async def redeem_promo_code(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    code: str,
) -> tuple[PromoResult, int]:
    """Активировать промокод, начислив кредиты. Возвращает (результат, кредиты).

    Атомарность и защита от гонок:
    - Строка ``PromoRedemptionModel`` с уникальным ``(promo, user)`` вставляется
      первой — повторная активация тем же пользователем ловится как
      :class:`IntegrityError` до расхода лимита.
    - Глобальный счётчик ``used_activations`` инкрементируется условным UPDATE с
      проверкой лимита и срока: при исчерпании ``rowcount == 0`` и вся операция
      откатывается, кредиты не начисляются.
    - Начисление кредитов и оба изменения фиксируются одним ``commit``.
    """
    code_norm = normalize_code(code)
    if not code_norm or len(code_norm) > MAX_CODE_LENGTH:
        return PromoResult.NOT_FOUND, 0

    promo = await session.scalar(
        select(PromoCodeModel).where(PromoCodeModel.code == code_norm)
    )
    if promo is None or not promo.is_active:
        return PromoResult.NOT_FOUND, 0

    now = datetime.now(UTC).replace(tzinfo=None)
    if promo.expires_at is not None and promo.expires_at <= now:
        return PromoResult.EXPIRED, 0

    credits = promo.credits

    # 1) Резервируем активацию за пользователем (unique промо+юзер).
    session.add(
        PromoRedemptionModel(
            promo_idpk=promo.id,
            user_idpk=user.id,
            credits=credits,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return PromoResult.ALREADY_USED, 0

    # 2) Занимаем слот в глобальном лимите (0 = без лимита) с проверкой срока.
    slot = await session.execute(
        update(PromoCodeModel)
        .where(
            PromoCodeModel.id == promo.id,
            PromoCodeModel.is_active.is_(True),
            or_(
                PromoCodeModel.max_activations == 0,
                PromoCodeModel.used_activations < PromoCodeModel.max_activations,
            ),
            or_(
                PromoCodeModel.expires_at.is_(None),
                PromoCodeModel.expires_at > now,
            ),
        )
        .values(used_activations=PromoCodeModel.used_activations + 1)
    )
    if cast(CursorResult, slot).rowcount == 0:
        await session.rollback()
        return PromoResult.EXHAUSTED, 0

    # 3) Начисляем кредиты и фиксируем всё одной транзакцией.
    await session.execute(
        update(UserModel)
        .where(UserModel.id == user.id)
        .values(credits=UserModel.credits + credits)
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось зафиксировать активацию промокода %s", code_norm)
        return PromoResult.ERROR, 0

    await UserRD.delete(redis, user.user_id)
    return PromoResult.OK, credits


async def create_promo_code(
    *,
    session: AsyncSession,
    code: str,
    credits: int,
    max_activations: int,
    expires_at: datetime | None,
    created_by: int | None,
) -> bool:
    """Создать промокод. Возвращает False, если код с таким именем уже есть."""
    promo = PromoCodeModel(
        code=normalize_code(code),
        credits=credits,
        max_activations=max_activations,
        expires_at=expires_at,
        created_by=created_by,
    )
    session.add(promo)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True
