from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import select

from bot.db.func import refund_user_credits
from bot.db.models import UserModel
from bot.db.redis.user_model import UserRD

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

FILENAME_LIMIT = 80


async def _send_tracks(
    bot: Bot,
    chat_id: int,
    filename_base: str,
    data: dict[str, Any],
) -> list[str]:
    response = data.get("response", {}) if isinstance(data, dict) else {}
    tracks = response.get("sunoData") or []
    if not tracks:
        logger.warning("Не получены треки для базового имени %s", filename_base)
        await bot.send_message(chat_id, "Готово, но ссылки на аудио не получены.")
        return False

    total = len(tracks)
    sent_any = False
    file_ids: list[str] = []
    for idx, track in enumerate(tracks, start=1):
        audio_url = track.get("audioUrl") or track.get("streamAudioUrl")
        if not audio_url:
            continue

        try:
            audio_bytes = await _download_audio(audio_url)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            logger.warning("Не удалось скачать аудио %s: %s", audio_url, err)
            await bot.send_message(
                chat_id,
                f"Не удалось скачать аудио для трека {idx}.",
            )
            continue

        filename = _build_filename(filename_base, idx, total, audio_url)
        try:
            message = await bot.send_audio(
                chat_id=chat_id,
                audio=BufferedInputFile(audio_bytes, filename=filename),
            )
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
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
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


async def _refund_credits(
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
