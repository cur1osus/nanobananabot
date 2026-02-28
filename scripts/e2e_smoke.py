from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from aiogram import BaseMiddleware, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.db.redis.user_model import UserRD
from bot.handlers import router as handlers_router
from bot.keyboards.factories import MenuAction
from tests.aiogram_test_utils import FakeBot


class InjectDataMiddleware(BaseMiddleware):
    def __init__(self, *, user, session, redis, sessionmaker) -> None:
        self._user = user
        self._session = session
        self._redis = redis
        self._sessionmaker = sessionmaker

    async def __call__(self, handler, event, data):  # type: ignore[override]
        data["user"] = self._user
        data["session"] = self._session
        data["redis"] = self._redis
        data["sessionmaker"] = self._sessionmaker
        return await handler(event, data)


def _make_message(bot: FakeBot, text: str) -> Message:
    message = Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="Test"),
        text=text,
    )
    return message.as_(bot)


def _make_callback(bot: FakeBot, data: str) -> CallbackQuery:
    message = _make_message(bot, "menu")
    callback = CallbackQuery(
        id="1",
        from_user=User(id=1, is_bot=False, first_name="Test"),
        chat_instance="1",
        data=data,
        message=message,
    )
    callback.as_(bot)
    message.as_(bot)
    return callback


def _has_call(bot: FakeBot, method: str) -> bool:
    return any(call.__class__.__name__ == method for call in bot.session.calls)


async def main() -> None:
    bot = FakeBot()
    now = datetime.now()
    user = UserRD(
        id=100,
        user_id=100,
        name="Test",
        username="test",
        credits=10,
        role="user",
        referrer_id=None,
        balance=0,
        registration_datetime=now,
        last_active=now,
    )
    session = AsyncMock()
    redis = AsyncMock()
    sessionmaker = AsyncMock()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(handlers_router)
    dp.update.outer_middleware(
        InjectDataMiddleware(
            user=user,
            session=session,
            redis=redis,
            sessionmaker=sessionmaker,
        )
    )

    steps = [
        ("/start", Update(update_id=1, message=_make_message(bot, "/start")), "SendMessage"),
        (
            "menu_home",
            Update(
                update_id=2,
                callback_query=_make_callback(bot, MenuAction(action="home").pack()),
            ),
            "EditMessageText",
        ),
        (
            "menu_how",
            Update(
                update_id=3,
                callback_query=_make_callback(bot, MenuAction(action="how").pack()),
            ),
            "EditMessageText",
        ),
        (
            "menu_topup",
            Update(
                update_id=4,
                callback_query=_make_callback(bot, MenuAction(action="topup").pack()),
            ),
            "EditMessageText",
        ),
        (
            "menu_earn",
            Update(
                update_id=5,
                callback_query=_make_callback(bot, MenuAction(action="earn").pack()),
            ),
            "EditMessageText",
        ),
    ]

    session.scalar.side_effect = [0, 0, 0, 0]

    for label, update, expected in steps:
        bot.session.calls.clear()
        await dp.feed_update(bot, update)
        if not _has_call(bot, expected):
            raise SystemExit(f"E2E шаг {label} не вызвал {expected}")

    print("E2E smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
