from __future__ import annotations

import json
import logging
import math
from typing import TYPE_CHECKING, Any

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.background_tasks import MIN_POLL_TIMEOUT
from bot.db.enum import MusicTaskStatus, UserRole
from bot.db.func import charge_user_credits, refund_user_credits
from bot.db.models import MusicTaskModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction, MyTrackAction, MyTracksPage
from bot.keyboards.inline import ik_main
from bot.keyboards.music import ik_my_track_detail, ik_my_tracks_list
from bot.utils.background_task_helpers import _build_filename, _download_audio
from bot.utils.messaging import edit_or_answer
from bot.utils.music_topics import get_music_topic_option
from bot.utils.suno_api import SunoAPIError, build_suno_client
from bot.utils.texts import (
    MY_TRACKS_EMPTY_TEXT,
    MY_TRACKS_MENU_TEXT,
    music_generation_started_text,
    my_tracks_details_text,
    my_tracks_lyrics_text,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker

router = Router()
logger = logging.getLogger(__name__)

PAGE_SIZE = 8

STATUS_LABELS = {
    MusicTaskStatus.PENDING.value: "Ожидает",
    MusicTaskStatus.PROCESSING.value: "Генерируется",
    MusicTaskStatus.SUCCESS.value: "Готово",
    MusicTaskStatus.ERROR.value: "Ошибка",
    MusicTaskStatus.TIMEOUT.value: "Таймаут",
}
STATUS_PREFIXES = {
    MusicTaskStatus.PENDING.value: "⏳ ",
    MusicTaskStatus.PROCESSING.value: "⏳ ",
    MusicTaskStatus.SUCCESS.value: "",
    MusicTaskStatus.ERROR.value: "⚠️ ",
    MusicTaskStatus.TIMEOUT.value: "⌛ ",
}


@router.callback_query(MenuAction.filter(F.action == "tracks"))
async def menu_tracks(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await query.answer()
    await state.clear()
    await _render_tracks_page(query, user, session, page=1)


@router.callback_query(MyTracksPage.filter())
async def menu_tracks_page(
    query: CallbackQuery,
    callback_data: MyTracksPage,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await query.answer()
    await _render_tracks_page(query, user, session, page=callback_data.page)


@router.callback_query(MyTrackAction.filter(F.action == "detail"))
async def track_detail(
    query: CallbackQuery,
    callback_data: MyTrackAction,
    user: UserRD,
    session: AsyncSession,
) -> None:
    task = await _get_user_task(session, user.id, callback_data.track_id)
    if not task:
        await query.answer("Трек не найден.", show_alert=True)
        return
    await query.answer()

    status_label = STATUS_LABELS.get(task.status, task.status)
    base_title = (
        task.filename_base.strip() if task.filename_base else f"Трек #{task.id}"
    )
    file_ids = _load_audio_file_ids(task)
    song_type = _song_type_from_task(task)
    genre = _genre_from_task(task)

    if task.status != MusicTaskStatus.SUCCESS.value:
        text = my_tracks_details_text(
            title=base_title,
            created_at=task.created_at,
            status_label=status_label,
            song_type=song_type,
            genre=genre,
        )
        can_retry = task.status in (
            MusicTaskStatus.TIMEOUT.value,
            MusicTaskStatus.ERROR.value,
        ) and bool(task.prompt)
        await edit_or_answer(
            query,
            text=text,
            reply_markup=await ik_my_track_detail(
                task.id, show_lyrics=False, show_audio=False, show_retry=can_retry
            ),
        )
        return

    try:
        payload = await _fetch_task_payload(task.task_id)
    except SunoAPIError as err:
        logger.warning("Не удалось получить данные трека %s: %s", task.task_id, err)
        text = my_tracks_details_text(
            title=base_title,
            created_at=task.created_at,
            status_label=status_label,
            song_type=song_type,
            genre=genre,
        )
        # Show audio button if file_ids exist, otherwise don't show it
        show_audio = bool(file_ids)
        await edit_or_answer(
            query,
            text=text,
            reply_markup=await ik_my_track_detail(
                task.id, show_lyrics=False, show_audio=show_audio
            ),
        )
        return

    tracks = _extract_tracks(payload)
    title = _pick_title(tracks, fallback=base_title)
    song_type = song_type or _pick_song_type(payload, tracks)
    genre = genre or _pick_genre(payload, tracks)

    text = my_tracks_details_text(
        title=title,
        created_at=task.created_at,
        song_type=song_type,
        genre=genre,
    )
    await edit_or_answer(
        query,
        text=text,
        reply_markup=await ik_my_track_detail(
            task.id, show_lyrics=True, show_audio=True
        ),
    )


@router.callback_query(MyTrackAction.filter(F.action == "send_audio"))
async def track_send_audio(
    query: CallbackQuery,
    callback_data: MyTrackAction,
    user: UserRD,
    session: AsyncSession,
) -> None:
    task = await _get_user_task(session, user.id, callback_data.track_id)
    if not task:
        await query.answer("Трек не найден.", show_alert=True)
        return
    if task.status != MusicTaskStatus.SUCCESS.value:
        await query.answer("Трек ещё не готов.", show_alert=True)
        return

    base_title = (
        task.filename_base.strip() if task.filename_base else f"Трек #{task.id}"
    )
    file_ids = _load_audio_file_ids(task)

    try:
        payload = await _fetch_task_payload(task.task_id)
    except SunoAPIError as err:
        logger.warning("Не удалось получить данные трека %s: %s", task.task_id, err)
        message = query.message
        if message and file_ids:
            await query.answer()
            await _send_track_audio(query, [], title=base_title, file_ids=file_ids)
        else:
            await query.answer("Не удалось получить аудиофайлы.", show_alert=True)
        return

    await query.answer()
    tracks = _extract_tracks(payload)
    title = _pick_title(tracks, fallback=base_title)
    await _send_track_audio(query, tracks, title=title, file_ids=file_ids)


@router.callback_query(MyTrackAction.filter(F.action == "lyrics"))
async def track_lyrics(
    query: CallbackQuery,
    callback_data: MyTrackAction,
    user: UserRD,
    session: AsyncSession,
) -> None:
    task = await _get_user_task(session, user.id, callback_data.track_id)
    if not task:
        await query.answer("Трек не найден.", show_alert=True)
        return
    if task.status != MusicTaskStatus.SUCCESS.value:
        await query.answer("Трек ещё не готов.", show_alert=True)
        return

    fallback_title = (
        task.filename_base.strip() if task.filename_base else f"Трек #{task.id}"
    )

    # Check if lyrics are already saved in DB
    lyrics = task.lyrics
    title = fallback_title

    if not lyrics:
        # If not in DB, fetch from API
        try:
            payload = await _fetch_task_payload(task.task_id)
        except SunoAPIError as err:
            logger.warning("Не удалось получить текст трека %s: %s", task.task_id, err)
            await query.answer("Не удалось получить текст песни.", show_alert=True)
            return

        tracks = _extract_tracks(payload)
        title = _pick_title(tracks, fallback=fallback_title)
        lyrics = _pick_lyrics(payload, tracks)

        if not lyrics:
            await query.answer("Текст песни не найден.", show_alert=True)
            return

        # Save lyrics to DB for future use
        task.lyrics = lyrics
        await session.commit()

    message = query.message
    if not message:
        await query.answer()
        return

    await query.answer()
    for chunk in _split_text(my_tracks_lyrics_text(title=title, lyrics=lyrics)):
        await message.answer(chunk)


async def _render_tracks_page(
    query: CallbackQuery,
    user: UserRD,
    session: AsyncSession,
    *,
    page: int,
) -> None:
    total = await session.scalar(
        select(func.count(MusicTaskModel.id)).where(MusicTaskModel.user_idpk == user.id)
    )
    total = int(total or 0)

    if total == 0:
        await edit_or_answer(
            query,
            text=MY_TRACKS_EMPTY_TEXT,
            reply_markup=await ik_my_tracks_list([], page=1, total_pages=1),
        )
        return

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    tasks = (
        await session.scalars(
            select(MusicTaskModel)
            .where(MusicTaskModel.user_idpk == user.id)
            .order_by(MusicTaskModel.created_at.desc())
            .limit(PAGE_SIZE)
            .offset(offset)
        )
    ).all()

    items = []
    for task in tasks:
        title = task.filename_base.strip() if task.filename_base else ""
        if not title:
            title = f"Трек #{task.id}"
        prefix = STATUS_PREFIXES.get(task.status, "")
        items.append((task.id, f"{prefix}{title}"))

    text = MY_TRACKS_MENU_TEXT
    if total_pages > 1:
        text = f"{text}\n\nСтраница {page} из {total_pages}"

    await edit_or_answer(
        query,
        text=text,
        reply_markup=await ik_my_tracks_list(items, page=page, total_pages=total_pages),
    )


async def _get_user_task(
    session: AsyncSession,
    user_idpk: int,
    track_id: int,
) -> MusicTaskModel | None:
    return await session.scalar(
        select(MusicTaskModel).where(
            MusicTaskModel.id == track_id,
            MusicTaskModel.user_idpk == user_idpk,
        )
    )


def _load_audio_file_ids(task: MusicTaskModel) -> list[str]:
    raw = task.audio_file_ids
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = raw

    if isinstance(data, list):
        return [str(item).strip() for item in data if str(item).strip()]
    if isinstance(data, str) and data.strip():
        return [data.strip()]
    return []


async def _fetch_task_payload(task_id: str) -> dict[str, Any]:
    client = build_suno_client()
    details = await client.get_task_details(task_id)
    return details.get("data", {}) or {}


def _extract_tracks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response") or {}
    if not isinstance(response, dict):
        return []
    tracks = response.get("sunoData") or response.get("data") or []
    if not isinstance(tracks, list):
        return []
    return [track for track in tracks if isinstance(track, dict)]


def _pick_title(tracks: list[dict[str, Any]], *, fallback: str) -> str:
    for track in tracks:
        title = str(
            track.get("title") or track.get("songName") or track.get("name") or ""
        )
        if title.strip():
            return title.strip()
    return fallback.strip() or "Трек"


def _pick_song_type(
    payload: dict[str, Any], tracks: list[dict[str, Any]]
) -> str | None:
    for track in tracks:
        value = track.get("prompt") or track.get("description")
        if value:
            return str(value).strip()
    value = payload.get("prompt") or payload.get("description")
    return str(value).strip() if value else None


def _pick_genre(payload: dict[str, Any], tracks: list[dict[str, Any]]) -> str | None:
    for track in tracks:
        value = track.get("tags") or track.get("style") or track.get("genre")
        if value:
            return _normalize_tags(value)
    value = payload.get("style") or payload.get("genre")
    return _normalize_tags(value) if value else None


def _normalize_tags(value: Any) -> str:
    if isinstance(value, list):
        tags = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(tags)
    return str(value).strip()


def _pick_lyrics(payload: dict[str, Any], tracks: list[dict[str, Any]]) -> str | None:
    for track in tracks:
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
    value = payload.get("lyrics") or payload.get("lyric") or payload.get("text")
    return str(value).strip() if value else None


def _song_type_from_task(task: MusicTaskModel) -> str | None:
    if task.instrumental:
        return "🎹 Инструментал"
    topic_key = (task.topic_key or "").strip()
    if not topic_key:
        return None
    option = get_music_topic_option(topic_key)
    if not option:
        return None
    return f"{option.emoji} {option.label}, {option.type_suffix}"


def _genre_from_task(task: MusicTaskModel) -> str | None:
    style = (task.style or "").strip()
    return style or None


@router.callback_query(MyTrackAction.filter(F.action == "retry"))
async def track_retry(
    query: CallbackQuery,
    callback_data: MyTrackAction,
    user: UserRD,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    task = await _get_user_task(session, user.id, callback_data.track_id)
    if not task:
        await query.answer("Трек не найден.", show_alert=True)
        return
    if not task.prompt:
        await query.answer("Нет данных для повтора генерации.", show_alert=True)
        return

    await query.answer()

    credits_cost = task.credits_cost
    if not await charge_user_credits(
        session=session, redis=redis, user=user, amount=credits_cost
    ):
        await query.answer(
            f"Недостаточно кредитов. Нужно {credits_cost}.", show_alert=True
        )
        return

    try:
        client = build_suno_client()
        new_task_id = await client.generate_music(
            prompt=task.prompt,
            custom_mode=bool(task.custom_mode),
            instrumental=bool(task.instrumental),
            style=task.style or "",
            title=task.filename_base or "",
        )
    except SunoAPIError as err:
        logger.warning("Retry генерации не удался task_id=%s: %s", task.task_id, err)
        await refund_user_credits(
            session=session, redis=redis, user=user, amount=credits_cost
        )
        await query.message.answer("Не удалось запустить генерацию. Попробуйте позже.")
        return

    user_db = await session.scalar(
        select(UserModel).where(UserModel.user_id == user.user_id)
    )
    if not user_db:
        await refund_user_credits(
            session=session, redis=redis, user=user, amount=credits_cost
        )
        await query.message.answer("Ошибка при создании задачи. Попробуйте позже.")
        return

    new_task = MusicTaskModel(
        user_idpk=user_db.id,
        task_id=new_task_id,
        chat_id=task.chat_id,
        filename_base=task.filename_base,
        status=MusicTaskStatus.PENDING.value,
        errors=0,
        credits_cost=credits_cost,
        poll_timeout=max(client.poll_timeout, MIN_POLL_TIMEOUT),
        topic_key=task.topic_key,
        style=task.style,
        prompt_source=task.prompt_source,
        prompt=task.prompt,
        custom_mode=bool(task.custom_mode),
        instrumental=bool(task.instrumental),
    )
    try:
        session.add(new_task)
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось сохранить retry-задачу %s: %s", new_task_id, err)
        await refund_user_credits(
            session=session, redis=redis, user=user, amount=credits_cost
        )
        await query.message.answer("Ошибка при сохранении задачи. Попробуйте позже.")
        return

    await query.message.answer(
        music_generation_started_text(new_task_id, task.filename_base or "Трек"),
        reply_markup=await ik_main(is_admin=user.role == UserRole.ADMIN.value),
    )


async def _send_track_audio(
    query: CallbackQuery,
    tracks: list[dict[str, Any]],
    *,
    title: str,
    file_ids: list[str] | None = None,
) -> None:
    message = query.message
    if not message:
        return

    if file_ids:
        for idx, file_id in enumerate(file_ids, start=1):
            try:
                await message.answer_audio(audio=file_id)
            except Exception as err:
                logger.warning("Не удалось отправить аудио %s: %s", file_id, err)
                await message.answer(f"Не удалось отправить файл для трека {idx}.")
        return

    audio_urls: list[str] = []
    for track in tracks:
        url = (
            track.get("audioUrl")
            or track.get("streamAudioUrl")
            or track.get("audio_url")
        )
        if url and isinstance(url, str):
            audio_urls.append(url)
    if not audio_urls:
        await message.answer("Аудиофайлы для трека не найдены.")
        return

    total = len(audio_urls)
    for idx, audio_url in enumerate(audio_urls, start=1):
        try:
            audio_bytes = await _download_audio(audio_url)
        except (TimeoutError, aiohttp.ClientError) as err:
            logger.warning("Не удалось скачать аудио %s: %s", audio_url, err)
            await message.answer(f"Не удалось скачать аудио для трека {idx}.")
            continue

        filename = _build_filename(title, idx, total, audio_url)
        try:
            await message.answer_audio(
                audio=BufferedInputFile(audio_bytes, filename=filename),
            )
        except Exception as err:
            logger.warning("Не удалось отправить аудиофайл %s: %s", filename, err)
            await message.answer(f"Не удалось отправить файл для трека {idx}.")


def _split_text(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > limit and current:
            chunks.append("".join(current).rstrip())
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current).rstrip())
    return chunks
