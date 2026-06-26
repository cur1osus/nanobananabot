from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, Self

import msgspec
import msgspec.msgpack
from redis.asyncio import Redis
from redis.typing import ExpiryT

from bot.utils.alchemy_struct import AlchemyStruct

ENCODER: Final[msgspec.msgpack.Encoder] = msgspec.msgpack.Encoder()

# Sorted set: member = user_id, score = unix-время последней активности.
# Позволяет считать онлайн через ZCOUNT за O(log N) без сканирования ключей.
ACTIVE_ZSET_KEY: Final[str] = "users:active"


class UserRD(msgspec.Struct, AlchemyStruct["UserRD"], kw_only=True, array_like=True):
    id: int

    user_id: int
    name: str
    username: str | None = msgspec.field(default=None)
    credits: int
    role: str

    referrer_id: int | None = msgspec.field(default=None)
    balance: int = 0

    registration_datetime: datetime
    last_active: datetime

    @classmethod
    def key(cls, user_id: int | str) -> str:
        return f"{cls.__name__}:{user_id}"

    @classmethod
    async def get(cls, redis: Redis, user_id: int | str) -> Self | None:
        data = await redis.get(cls.key(user_id))
        if data:
            try:
                return msgspec.msgpack.decode(data, type=cls)
            except (msgspec.DecodeError, msgspec.ValidationError):
                await redis.delete(cls.key(user_id))
                return None
        return None

    async def save(self, redis: Redis, ttl: ExpiryT = timedelta(days=1)) -> str:
        return await redis.setex(self.key(self.user_id), ttl, ENCODER.encode(self))

    async def update_last_active(self, redis: Redis) -> None:
        """Update last_active timestamp and save to Redis."""
        now = datetime.now()
        self.last_active = now
        await self.save(redis)
        await redis.zadd(ACTIVE_ZSET_KEY, {str(self.user_id): now.timestamp()})

    @classmethod
    async def delete(cls, redis: Redis, user_id: int | str) -> int:
        return await redis.delete(cls.key(user_id))

    @classmethod
    async def delete_all(cls, redis: Redis) -> int:
        keys = await redis.keys(f"{cls.__name__}:*")
        return await redis.delete(*keys) if keys else 0

    @classmethod
    async def count_online(cls, redis: Redis, threshold_minutes: int = 5) -> int:
        """Count users active within the last ``threshold_minutes``.

        Использует sorted set :data:`ACTIVE_ZSET_KEY` и ZCOUNT — O(log N) без
        блокирующего ``KEYS``-сканирования всего пространства ключей.
        """
        cutoff = (datetime.now() - timedelta(minutes=threshold_minutes)).timestamp()
        return int(await redis.zcount(ACTIVE_ZSET_KEY, cutoff, "+inf"))
