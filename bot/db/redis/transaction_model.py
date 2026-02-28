from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, Self

import msgspec
import msgspec.msgpack
from redis.asyncio import Redis
from redis.typing import ExpiryT

from bot.utils.alchemy_struct import AlchemyStruct

ENCODER: Final[msgspec.msgpack.Encoder] = msgspec.msgpack.Encoder()


class TransactionRD(
    msgspec.Struct, AlchemyStruct["TransactionRD"], kw_only=True, array_like=True
):
    id: int
    user_idpk: int
    manager_id: int | None = msgspec.field(default=None)
    type: str
    method: str
    plan: str
    amount: int
    currency: str
    credits: int
    status: str
    payload: str
    telegram_charge_id: str | None = msgspec.field(default=None)
    provider_charge_id: str | None = msgspec.field(default=None)
    details: str | None = msgspec.field(default=None)
    created_at: datetime

    @classmethod
    def key(cls, transaction_id: int | str) -> str:
        return f"{cls.__name__}:{transaction_id}"

    @classmethod
    async def get(cls, redis: Redis, transaction_id: int | str) -> Self | None:
        data = await redis.get(cls.key(transaction_id))
        if data:
            try:
                return msgspec.msgpack.decode(data, type=cls)
            except (msgspec.DecodeError, msgspec.ValidationError):
                await redis.delete(cls.key(transaction_id))
                return None
        return None

    async def save(self, redis: Redis, ttl: ExpiryT = timedelta(days=1)) -> str:
        return await redis.setex(self.key(self.id), ttl, ENCODER.encode(self))

    @classmethod
    async def delete(cls, redis: Redis, transaction_id: int | str) -> int:
        return await redis.delete(cls.key(transaction_id))

    @classmethod
    async def delete_all(cls, redis: Redis) -> int:
        keys = await redis.keys(f"{cls.__name__}:*")
        return await redis.delete(*keys) if keys else 0
