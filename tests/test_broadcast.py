from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from bot.handlers.cmds import broadcast


class _Forbidden(TelegramForbiddenError):
    """Имитация блокировки бота пользователем без конструирования метода."""

    def __init__(self) -> None:
        pass


class _RetryAfter(TelegramRetryAfter):
    """Имитация flood-control с нулевой паузой."""

    def __init__(self, retry_after: int = 0) -> None:
        self.retry_after = retry_after


class FakeBot:
    def __init__(self, behaviors: dict[int, object]) -> None:
        # behaviors[user_id]: исключение/None или список реакций по вызовам.
        self.behaviors = behaviors
        self.copy_calls: list[int] = []
        self.sent_messages: list[tuple[int, str]] = []

    async def copy_message(self, *, chat_id, from_chat_id, message_id):
        self.copy_calls.append(chat_id)
        beh = self.behaviors.get(chat_id)
        if isinstance(beh, list):
            beh = beh.pop(0) if beh else None
        if isinstance(beh, BaseException):
            raise beh
        return object()

    async def send_message(self, chat_id, text):
        self.sent_messages.append((chat_id, text))


class _SessionCM:
    def __init__(self, user_ids: list[int]) -> None:
        self._ids = user_ids

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def scalars(self, _stmt):
        return list(self._ids)


def _make_sessionmaker(user_ids: list[int]):
    return lambda: _SessionCM(user_ids)


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    monkeypatch.setattr(broadcast, "_SEND_DELAY", 0)


async def test_run_broadcast_delivers_and_reports():
    user_ids = [101, 102, 103, 104]
    bot = FakeBot(
        {
            101: None,  # успешная доставка
            102: _Forbidden(),  # заблокировал бота
            103: [_RetryAfter(0), None],  # flood-limit, затем успех
            104: RuntimeError("boom"),  # прочая ошибка
        }
    )

    await broadcast._run_broadcast(
        bot=bot,
        sessionmaker=_make_sessionmaker(user_ids),
        from_chat_id=999,
        message_id=42,
        admin_chat_id=999,
    )

    # 101 и 103 (со второй попытки) доставлены.
    assert bot.copy_calls.count(101) == 1
    assert bot.copy_calls.count(103) == 2  # первый вызов + повтор

    assert len(bot.sent_messages) == 1
    admin_id, report = bot.sent_messages[0]
    assert admin_id == 999
    assert "Всего пользователей: 4" in report
    assert "Доставлено: 2" in report
    assert "Заблокировали бота: 1" in report
    assert "Ошибок: 1" in report


async def test_run_broadcast_empty_audience_still_reports():
    bot = FakeBot({})

    await broadcast._run_broadcast(
        bot=bot,
        sessionmaker=_make_sessionmaker([]),
        from_chat_id=1,
        message_id=1,
        admin_chat_id=555,
    )

    assert bot.copy_calls == []
    assert len(bot.sent_messages) == 1
    admin_id, report = bot.sent_messages[0]
    assert admin_id == 555
    assert "Всего пользователей: 0" in report
    assert "Доставлено: 0" in report
