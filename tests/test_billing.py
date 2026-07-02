from __future__ import annotations

import json

import pytest

from bot.db.enum import GenerationTaskStatus
from bot.utils import billing
from bot.utils.billing import (
    MAX_ACTIVE_GENERATIONS_PER_USER,
    CreditsExhausted,
    GenerationBusy,
    enqueue_generation,
)


class FakeSession:
    """Минимальная сессия: возвращает число активных задач и копит add()."""

    def __init__(self, active_count: int = 0) -> None:
        self.active_count = active_count
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def scalar(self, *args, **kwargs) -> int:
        return self.active_count

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeUser:
    id = 1
    user_id = 1001


@pytest.fixture
def patch_credits(monkeypatch):
    """Подменяет charge_user_credits и собирает вызовы для проверок."""
    calls: dict[str, object] = {"charge": [], "charge_ok": True}

    async def fake_charge(*, session, redis, user, amount):
        calls["charge"].append(amount)  # type: ignore[union-attr]
        return calls["charge_ok"]

    monkeypatch.setattr(billing, "charge_user_credits", fake_charge)
    return calls


async def _enqueue(session, cost: int, kind: str = "image_edit"):
    return await enqueue_generation(
        session=session,
        redis=None,
        user=FakeUser(),
        kind=kind,
        cost=cost,
        chat_id=555,
        status_message_id=42,
        params={"prompt": "hi", "model_key": "nano"},
    )


async def test_enqueue_rejects_when_at_user_limit(patch_credits) -> None:
    # У пользователя уже максимум активных генераций.
    session = FakeSession(active_count=MAX_ACTIVE_GENERATIONS_PER_USER)

    with pytest.raises(GenerationBusy):
        await _enqueue(session, cost=2)

    # Кредиты не списаны, задача не создана.
    assert patch_credits["charge"] == []
    assert session.added == []


async def test_enqueue_no_credits_raises(patch_credits) -> None:
    patch_credits["charge_ok"] = False
    session = FakeSession(active_count=0)

    with pytest.raises(CreditsExhausted):
        await _enqueue(session, cost=3)

    # Списание было попыткой, но вернуло False.
    assert patch_credits["charge"] == [3]


async def test_enqueue_success_persists_queued_task(patch_credits) -> None:
    session = FakeSession(active_count=0)

    task = await _enqueue(session, cost=2, kind="video")

    assert patch_credits["charge"] == [2]
    assert task.status == GenerationTaskStatus.QUEUED.value
    assert task.kind == "video"
    assert task.credits_cost == 2
    assert task.chat_id == 555
    assert json.loads(task.params)["prompt"] == "hi"
    # Задача добавлена в сессию до списания (единый commit в charge).
    assert task in session.added


async def test_enqueue_allows_below_user_limit(patch_credits) -> None:
    # На единицу меньше лимита — постановка разрешена.
    session = FakeSession(active_count=MAX_ACTIVE_GENERATIONS_PER_USER - 1)

    task = await _enqueue(session, cost=1)

    assert task.status == GenerationTaskStatus.QUEUED.value
    assert patch_credits["charge"] == [1]
