from __future__ import annotations

import pytest

from bot.db.enum import GenerationTaskStatus
from bot.utils import billing
from bot.utils.billing import (
    CreditsExhausted,
    GenerationBusy,
    reserve_generation,
)


class FakeRedis:
    """Минимальный Redis для проверки логики замка."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        existed = key in self.store
        self.store.pop(key, None)
        return 1 if existed else 0


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeUser:
    id = 1
    user_id = 1001


def _lock_key() -> str:
    return billing._lock_key(FakeUser.user_id)


@pytest.fixture
def patch_credits(monkeypatch):
    """Подменяет charge/refund и собирает вызовы для проверок."""
    calls = {"charge": [], "refund": [], "charge_ok": True}

    async def fake_charge(*, session, redis, user, amount):
        calls["charge"].append(amount)
        return calls["charge_ok"]

    async def fake_refund(*, session, redis, user, amount):
        calls["refund"].append(amount)

    monkeypatch.setattr(billing, "charge_user_credits", fake_charge)
    monkeypatch.setattr(billing, "refund_user_credits", fake_refund)
    return calls


async def test_reserve_generation_rejects_parallel_run(patch_credits) -> None:
    redis = FakeRedis()
    redis.store[_lock_key()] = b"1"  # замок уже занят другой генерацией
    session = FakeSession()

    with pytest.raises(GenerationBusy):
        async with reserve_generation(
            session=session, redis=redis, user=FakeUser(), cost=2, kind="image_edit"
        ):
            pass

    # Кредиты не списаны, чужой замок не снят.
    assert patch_credits["charge"] == []
    assert _lock_key() in redis.store


async def test_reserve_generation_no_credits(patch_credits) -> None:
    patch_credits["charge_ok"] = False
    redis = FakeRedis()
    session = FakeSession()

    with pytest.raises(CreditsExhausted):
        async with reserve_generation(
            session=session, redis=redis, user=FakeUser(), cost=3, kind="image_edit"
        ):
            pass

    # Списание не прошло — возврата быть не должно, замок снят.
    assert patch_credits["charge"] == [3]
    assert patch_credits["refund"] == []
    assert _lock_key() not in redis.store


async def test_reserve_generation_success_marks_task(patch_credits) -> None:
    redis = FakeRedis()
    session = FakeSession()

    async with reserve_generation(
        session=session, redis=redis, user=FakeUser(), cost=2, kind="video"
    ) as task:
        assert task.status == GenerationTaskStatus.PROCESSING.value

    assert patch_credits["charge"] == [2]
    assert patch_credits["refund"] == []
    assert task.status == GenerationTaskStatus.SUCCESS.value
    assert _lock_key() not in redis.store


async def test_reserve_generation_refunds_on_error(patch_credits) -> None:
    redis = FakeRedis()
    session = FakeSession()

    with pytest.raises(RuntimeError):
        async with reserve_generation(
            session=session, redis=redis, user=FakeUser(), cost=4, kind="image_create"
        ) as task:
            raise RuntimeError("generation failed")

    # При ошибке кредиты возвращаются, задача помечается refunded, замок снят.
    assert patch_credits["charge"] == [4]
    assert patch_credits["refund"] == [4]
    assert task.status == GenerationTaskStatus.REFUNDED.value
    assert _lock_key() not in redis.store
