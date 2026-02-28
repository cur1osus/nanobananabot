from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import TransactionStatus
from bot.db.models import TransactionModel


async def get_manager_loads(
    session: AsyncSession,
    manager_ids: list[int],
) -> dict[int, int]:
    if not manager_ids:
        return {}

    stmt = (
        select(TransactionModel.manager_id, func.count(TransactionModel.id))
        .where(
            TransactionModel.manager_id.in_(manager_ids),
            TransactionModel.status == TransactionStatus.ASSIGNED.value,
        )
        .group_by(TransactionModel.manager_id)
    )
    rows = await session.execute(stmt)
    return {manager_id: count for manager_id, count in rows}


def pick_manager_id(
    manager_ids: list[int],
    loads: dict[int, int],
) -> int | None:
    if not manager_ids:
        return None

    min_load = min(loads.get(manager_id, 0) for manager_id in manager_ids)
    for manager_id in manager_ids:
        if loads.get(manager_id, 0) == min_load:
            return manager_id
    return manager_ids[0]
