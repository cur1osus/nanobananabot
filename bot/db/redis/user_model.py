from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, Self

import msgspec
import msgspec.msgpack
from redis.asyncio import Redis
from redis.typing import ExpiryT

from bot.utils.alchemy_struct import AlchemyStruct

ENCODER: Final[msgspec.msgpack.Encoder] = msgspec.msgpack.Encoder()


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
        self.last_active = datetime.now()
        await self.save(redis)

    @classmethod
    async def delete(cls, redis: Redis, user_id: int | str) -> int:
        return await redis.delete(cls.key(user_id))

    @classmethod
    async def delete_all(cls, redis: Redis) -> int:
        keys = await redis.keys(f"{cls.__name__}:*")
        return await redis.delete(*keys) if keys else 0

    @classmethod
    async def count_online(cls, redis: Redis, threshold_minutes: int = 5) -> int:
        """
        Count users who were active within the last threshold_minutes.

        Args:
            redis: Redis connection
            threshold_minutes: Time window in minutes to consider user as online (default: 5)

        Returns:
            Number of online users
        """
        keys = await redis.keys(f"{cls.__name__}:*")
        if not keys:
            return 0

        now = datetime.now()
        threshold = timedelta(minutes=threshold_minutes)
        online_count = 0

        for key in keys:
            data = await redis.get(key)
            if data:
                try:
                    user = msgspec.msgpack.decode(data, type=cls)
                    if now - user.last_active <= threshold:
                        online_count += 1
                except (msgspec.DecodeError, msgspec.ValidationError):
                    continue

        return online_count
