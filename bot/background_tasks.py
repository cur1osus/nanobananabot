from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING, Any, cast

from aiogram import Bot
from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import selectinload

from bot.db.enum import GenerationTaskStatus, MusicTaskStatus
from bot.db.models import GenerationTaskModel, MusicTaskModel
from bot.scheduler import default_scheduler
from bot.utils.background_task_helpers import (
    refund_task_credits,
    send_tracks,
    spawn_background_task,
)
from bot.utils.generation_runner import run_generation_task
from bot.utils.gift_credits import run_gift_expiry
from bot.utils.suno_api import SunoAPIError, build_suno_client

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 10
MAX_TASKS_PER_RUN = 20
MAX_POLL_ERRORS = 3
MIN_POLL_TIMEOUT = 600

# Сгорание подарочных кредитов проверяем раз в 5 минут: точность «до минуты»
# здесь не нужна, а нагрузка на БД остаётся минимальной.
GIFT_EXPIRY_INTERVAL_SECONDS = 300

# Очередь генераций фото/видео опрашиваем часто (запуск дешёвый — лишь claim и
# spawn), но число одновременно выполняемых генераций ограничиваем, чтобы не
# перегружать провайдеров и память.
GENERATION_POLL_SECONDS = 3
# Глобальный потолок одновременных генераций держим выше лимита на пользователя
# (billing.MAX_ACTIVE_GENERATIONS_PER_USER=3), чтобы один пользователь со
# студийной очередью не занимал все слоты и не блокировал остальных.
MAX_CONCURRENT_GENERATIONS = 6

# id задач, исполняемых прямо сейчас (в spawned-задачах), — чтобы диспетчер не
# подхватил одну и ту же дважды.
_inflight_generations: set[int] = set()
_GENERATION_DISPATCH_LOCK = asyncio.Lock()

TERMINAL_STATUSES = {
    "SUCCESS",
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "CALLBACK_EXCEPTION",
    "SENSITIVE_WORD_ERROR",
}
STATUS_MESSAGES = {
    "CREATE_TASK_FAILED": "Не удалось создать задачу генерации.",
    "GENERATE_AUDIO_FAILED": "Не удалось сгенерировать аудио.",
    "CALLBACK_EXCEPTION": "Произошла ошибка при обработке результата.",
    "SENSITIVE_WORD_ERROR": "В тексте обнаружены запрещенные слова.",
}

_POLL_LOCK = asyncio.Lock()


def schedule_music_polling(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    if default_scheduler.get_jobs(tag="music_poll"):
        return
    default_scheduler.every(POLL_INTERVAL_SECONDS).seconds.do(
        poll_music_tasks,
        bot=bot,
        sessionmaker=sessionmaker,
        redis=redis,
    ).tag("music_poll")


def schedule_generation_worker(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    if default_scheduler.get_jobs(tag="generation_worker"):
        return
    default_scheduler.every(GENERATION_POLL_SECONDS).seconds.do(
        dispatch_generation_tasks,
        bot=bot,
        sessionmaker=sessionmaker,
        redis=redis,
    ).tag("generation_worker")


async def dispatch_generation_tasks(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    """Забрать задачи из очереди и запустить их выполнение параллельно.

    Сам диспетчер ничего не ждёт: атомарно переводит ``queued`` → ``processing``
    и запускает исполнитель в фоне. Параллельность ограничена
    ``MAX_CONCURRENT_GENERATIONS``.
    """
    if _GENERATION_DISPATCH_LOCK.locked():
        return
    async with _GENERATION_DISPATCH_LOCK:
        free = MAX_CONCURRENT_GENERATIONS - len(_inflight_generations)
        if free <= 0:
            return
        async with sessionmaker() as session:
            ids = (
                await session.scalars(
                    select(GenerationTaskModel.id)
                    .where(
                        GenerationTaskModel.status == GenerationTaskStatus.QUEUED.value
                    )
                    .order_by(GenerationTaskModel.created_at.asc())
                    .limit(free)
                )
            ).all()
            for task_id in ids:
                if task_id in _inflight_generations:
                    continue
                result = await session.execute(
                    update(GenerationTaskModel)
                    .where(
                        GenerationTaskModel.id == task_id,
                        GenerationTaskModel.status == GenerationTaskStatus.QUEUED.value,
                    )
                    .values(status=GenerationTaskStatus.PROCESSING.value)
                )
                await session.commit()
                if cast(CursorResult, result).rowcount == 0:
                    continue
                _inflight_generations.add(task_id)
                spawn_background_task(
                    _run_and_release(
                        bot=bot,
                        sessionmaker=sessionmaker,
                        redis=redis,
                        task_id=task_id,
                    ),
                    name=f"generation:{task_id}",
                )


async def _run_and_release(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    task_id: int,
) -> None:
    try:
        await run_generation_task(
            bot=bot,
            sessionmaker=sessionmaker,
            redis=redis,
            task_id=task_id,
        )
    finally:
        _inflight_generations.discard(task_id)


def schedule_gift_expiry(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    if default_scheduler.get_jobs(tag="gift_expiry"):
        return
    default_scheduler.every(GIFT_EXPIRY_INTERVAL_SECONDS).seconds.do(
        run_gift_expiry,
        sessionmaker=sessionmaker,
        redis=redis,
    ).tag("gift_expiry")


async def poll_music_tasks(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    if _POLL_LOCK.locked():
        return
    async with _POLL_LOCK:
        async with sessionmaker() as session:
            await _poll_music_tasks_inner(
                bot=bot,
                session=session,
                sessionmaker=sessionmaker,
                redis=redis,
            )


async def _poll_music_tasks_inner(
    *,
    bot: Bot,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(seconds=POLL_INTERVAL_SECONDS)
    stmt = (
        select(MusicTaskModel)
        .where(
            MusicTaskModel.status.in_(
                [MusicTaskStatus.PENDING.value, MusicTaskStatus.PROCESSING.value]
            )
        )
        .where(
            or_(
                MusicTaskModel.last_polled_at.is_(None),
                MusicTaskModel.last_polled_at < cutoff,
            )
        )
        .order_by(MusicTaskModel.created_at.asc())
        .limit(MAX_TASKS_PER_RUN)
        .options(selectinload(MusicTaskModel.user))
    )
    tasks = (await session.scalars(stmt)).all()
    if not tasks:
        return

    client = build_suno_client()

    for task in tasks:
        await _poll_single_task(
            bot=bot,
            session=session,
            sessionmaker=sessionmaker,
            redis=redis,
            task=task,
            client=client,
            now=now,
        )


async def _poll_single_task(
    *,
    bot: Bot,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    task: MusicTaskModel,
    client,
    now: datetime,
) -> None:
    # Save user_id before any commit — after commit SQLAlchemy expires relationships,
    # causing MissingGreenlet if accessed later via lazy load in async context.
    user_id = task.user.user_id

    task.last_polled_at = now
    if task.status == MusicTaskStatus.PENDING.value:
        task.status = MusicTaskStatus.PROCESSING.value
    await session.commit()

    if _is_timed_out(task, now):
        await _handle_timeout(
            bot=bot,
            session=session,
            sessionmaker=sessionmaker,
            redis=redis,
            task=task,
            user_id=user_id,
        )
        return

    try:
        details = await client.get_task_details(task.task_id)
    except SunoAPIError as err:
        task.errors += 1
        await session.commit()
        logger.warning("Не удалось опросить задачу %s: %s", task.task_id, err)
        if task.errors >= MAX_POLL_ERRORS:
            await _handle_error(
                bot=bot,
                session=session,
                sessionmaker=sessionmaker,
                redis=redis,
                task=task,
                user_id=user_id,
                status_message="Не удалось получить результат генерации. Попробуйте позже.",
            )
        return

    data = details.get("data", {}) or {}
    status = str(data.get("status") or "").upper()

    if status == "SUCCESS":
        file_ids = await send_tracks(bot, task.chat_id, task.filename_base, data)
        task.status = MusicTaskStatus.SUCCESS.value
        if file_ids and not task.audio_file_ids:
            task.audio_file_ids = json.dumps(file_ids, ensure_ascii=False)
        if not task.lyrics:
            lyrics = _extract_lyrics(data)
            if lyrics:
                task.lyrics = lyrics
        await session.commit()
        return

    if status in TERMINAL_STATUSES:
        await _handle_error(
            bot=bot,
            session=session,
            sessionmaker=sessionmaker,
            redis=redis,
            task=task,
            user_id=user_id,
            status_message=STATUS_MESSAGES.get(
                status, "Генерация завершилась с ошибкой."
            ),
        )
        return

    task.status = MusicTaskStatus.PROCESSING.value
    await session.commit()


def _is_timed_out(task: MusicTaskModel, now: datetime) -> bool:
    timeout = max(task.poll_timeout, MIN_POLL_TIMEOUT)
    if not task.created_at:
        return False
    return (now - task.created_at).total_seconds() > timeout


async def _handle_timeout(
    *,
    bot: Bot,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    task: MusicTaskModel,
    user_id: int,
) -> None:
    task.status = MusicTaskStatus.TIMEOUT.value
    await session.commit()
    await refund_task_credits(
        sessionmaker=sessionmaker,
        redis=redis,
        user_id=user_id,
        amount=task.credits_cost,
    )
    await bot.send_message(task.chat_id, "Генерация превысила лимит ожидания.")


async def _handle_error(
    *,
    bot: Bot,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    task: MusicTaskModel,
    user_id: int,
    status_message: str,
) -> None:
    task.status = MusicTaskStatus.ERROR.value
    await session.commit()
    await refund_task_credits(
        sessionmaker=sessionmaker,
        redis=redis,
        user_id=user_id,
        amount=task.credits_cost,
    )
    await bot.send_message(task.chat_id, status_message)


def _extract_lyrics(data: dict[str, Any]) -> str | None:
    """Extract lyrics from Suno API response data."""
    response = data.get("response") or {}
    if not isinstance(response, dict):
        return None
    tracks = response.get("sunoData") or response.get("data") or []
    if not isinstance(tracks, list):
        return None

    for track in tracks:
        if not isinstance(track, dict):
            continue
        value = (
            track.get("lyrics")
            or track.get("lyric")
            or track.get("text")
            or track.get("content")
            or track.get("prompt")  # Suno API returns lyrics in "prompt" field
        )
        if value:
            return str(value).strip()
        meta = track.get("metadata")
        if isinstance(meta, dict):
            nested = meta.get("lyrics") or meta.get("lyric")
            if nested:
                return str(nested).strip()

    value = data.get("lyrics") or data.get("lyric") or data.get("text")
    return str(value).strip() if value else None
