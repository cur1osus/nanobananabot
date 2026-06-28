from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from aiogram import BaseMiddleware

from bot.db.func import get_user_model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram.types import TelegramObject, Update, User


# 777000 is Telegram's user id of service messages
TG_SERVICE_USER_ID: Final[int] = 777000


class ThrowUserMiddleware(BaseMiddleware):
    async def __call__(  # type: ignore[override]  # narrowed event type by design
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")

        if not user:
            return None

        if (
            event.event_type in ("message", "callback_query")
            and not user.is_bot
            and user.id != TG_SERVICE_USER_ID
        ):
            redis = data["redis"]
            user_model = await get_user_model(
                db_pool=data["sessionmaker"],
                redis=redis,
                user=user,
            )
            await user_model.update_last_active(redis)
            data["user"] = user_model

        return await handler(event, data)
