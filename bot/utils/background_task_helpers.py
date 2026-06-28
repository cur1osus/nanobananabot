from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile
from sqlalchemy import select

from bot.db.func import refund_user_credits
from bot.db.models import UserModel
from bot.db.redis.user_model import UserRD
from bot.utils.http import get_http_session

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

FILENAME_LIMIT = 80

# Event loop держит лишь СЛАБУЮ ссылку на задачи из create_task: без сильной
# ссылки сборщик мусора может уничтожить ещё работающую задачу прямо на лету
# (см. docs asyncio.create_task / ruff RUF006). Храним ссылки здесь и снимаем
# их по завершении, чтобы фоновые задачи (планировщик, рассылки) жили до конца.
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def spawn_background_task(
    coro: Coroutine[Any, Any, Any], *, name: str | None = None
) -> asyncio.Task[Any]:
    """Запустить fire-and-forget задачу, удержав ссылку до её завершения.

    Логирует необработанные исключения: иначе они молча тонут в задаче, на
    которую никто не делает ``await``.
    """
    task = asyncio.create_task(coro, name=name)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_on_background_task_done)
    return task


def _on_background_task_done(task: asyncio.Task[Any]) -> None:
    _BACKGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Фоновая задача %s завершилась с ошибкой", task.get_name(), exc_info=exc
        )


async def send_tracks(
    bot: Bot,
    chat_id: int,
    filename_base: str,
    data: dict[str, Any],
) -> list[str]:
    response = data.get("response", {}) if isinstance(data, dict) else {}
    tracks = response.get("sunoData") or response.get("data") or []
    if not tracks:
        logger.warning("Не получены треки для базового имени %s", filename_base)
        await bot.send_message(chat_id, "Готово, но ссылки на аудио не получены.")
        return []

    total = len(tracks)
    sent_any = False
    file_ids: list[str] = []
    for idx, track in enumerate(tracks, start=1):
        audio_url = track.get("audioUrl") or track.get("streamAudioUrl")
        if not audio_url:
            continue

        try:
            audio_bytes = await _download_audio(audio_url)
        except (TimeoutError, aiohttp.ClientError) as err:
            logger.warning("Не удалось скачать аудио %s: %s", audio_url, err)
            await bot.send_message(
                chat_id,
                f"Не удалось скачать аудио для трека {idx}.",
            )
            continue

        filename = _build_filename(filename_base, idx, total, audio_url)
        try:
            for attempt in range(3):
                try:
                    message = await bot.send_audio(
                        chat_id=chat_id,
                        audio=BufferedInputFile(audio_bytes, filename=filename),
                    )
                    break
                except TelegramRetryAfter as retry_err:
                    if attempt == 2:
                        raise
                    logger.warning(
                        "Rate limit при отправке трека %s, ждём %s сек",
                        filename,
                        retry_err.retry_after,
                    )
                    await asyncio.sleep(retry_err.retry_after)
            sent_any = True
            if message.audio and message.audio.file_id:
                file_ids.append(message.audio.file_id)
        except Exception as err:
            logger.warning("Не удалось отправить аудиофайл %s: %s", filename, err)
            await bot.send_message(
                chat_id,
                f"Не удалось отправить файл для трека {idx}.",
            )

    if not sent_any:
        logger.warning("Не удалось отправить аудиофайлы для %s", filename_base)
        await bot.send_message(chat_id, "Не удалось отправить ни одного файла.")
    return file_ids


async def _download_audio(url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=60)
    session = get_http_session()
    async with session.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return await response.read()


def _build_filename(base: str, index: int, total: int, url: str) -> str:
    base_name = _sanitize_filename(base) or "track"
    suffix = Path(urlparse(url).path).suffix or ".mp3"
    if total > 1:
        return f"{base_name}_{index}{suffix}"
    return f"{base_name}{suffix}"


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(ch if ch not in '\\/:*?"<>|\n\r\t' else "_" for ch in name)
    cleaned = " ".join(cleaned.split()).strip().rstrip(".")
    if len(cleaned) > FILENAME_LIMIT:
        cleaned = cleaned[:FILENAME_LIMIT].rstrip()
    return cleaned


async def refund_task_credits(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    user_id: int,
    amount: int,
) -> None:
    if amount <= 0:
        return
    async with sessionmaker() as session:
        user_db = await session.scalar(
            select(UserModel).where(UserModel.user_id == user_id)
        )
        if not user_db:
            logger.warning("Возврат пропущен, пользователь %s не найден", user_id)
            return
        user_rd = UserRD.from_orm(user_db)
        await refund_user_credits(
            session=session,
            redis=redis,
            user=user_rd,
            amount=amount,
        )
