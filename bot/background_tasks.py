from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import or_, select

from bot.db.enum import MusicTaskStatus
from bot.db.models import MusicTaskModel
from bot.scheduler import default_scheduler
from bot.utils.background_task_helpers import _refund_credits, _send_tracks
from bot.utils.suno_api import SunoAPIError, build_suno_client

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

POLL_INTERVAL_SECONDS = 10
MAX_TASKS_PER_RUN = 20
MAX_POLL_ERRORS = 3
MIN_POLL_TIMEOUT = 600

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
    now = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
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
                status_message="Не удалось получить результат генерации. Попробуйте позже.",
            )
        return

    data = details.get("data", {}) or {}
    status = str(data.get("status") or "").upper()

    if status == "SUCCESS":
        file_ids = await _send_tracks(bot, task.chat_id, task.filename_base, data)
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
) -> None:
    task.status = MusicTaskStatus.TIMEOUT.value
    await session.commit()
    await _refund_credits(
        sessionmaker=sessionmaker,
        redis=redis,
        user_id=task.user.user_id,
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
    status_message: str,
) -> None:
    task.status = MusicTaskStatus.ERROR.value
    await session.commit()
    await _refund_credits(
        sessionmaker=sessionmaker,
        redis=redis,
        user_id=task.user.user_id,
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
