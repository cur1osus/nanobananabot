from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.redis.user_model import UserRD
from bot.keyboards.enums import MusicBackTarget
from bot.keyboards.factories import MusicStyle
from bot.keyboards.inline import ik_back_home, ik_music_topic_text_menu
from bot.states import MusicGenerationState
from bot.utils.messaging import edit_or_answer
from bot.utils.music_helpers import start_generation
from bot.utils.music_state import get_music_data, update_music_data
from bot.utils.speech_recognition import (
    SpeechRecognitionError,
    transcribe_message_audio,
)
from bot.utils.texts import (
    MUSIC_INSTRUMENTAL_STYLE_CUSTOM_TEXT,
    MUSIC_PROMPT_INSTRUMENTAL_TEXT,
    MUSIC_STYLE_CUSTOM_TEXT,
    music_topic_custom_style_text,
    music_topic_text_menu_text,
)

router = Router()
logger = logging.getLogger(__name__)
MAX_STYLE_LEN = 1000


@router.message(MusicGenerationState.style)
async def style_received(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    style = (message.text or message.caption or "").strip()
    if not style and (message.voice or message.audio):
        try:
            style = await transcribe_message_audio(message, language="ru")
        except SpeechRecognitionError as err:
            logger.warning("Не удалось распознать аудио: %s", err)
            await message.answer(
                "Не удалось распознать аудио. Отправьте стиль текстом."
            )
            return
    if not style:
        await message.answer("Стиль не должен быть пустым.")
        return
    if len(style) > MAX_STYLE_LEN:
        await message.answer("Стиль слишком длинный. Укоротите до 1000 символов.")
        return

    await update_music_data(state, style=style)
    await start_generation_from_style(
        message,
        state,
        user=user,
        session=session,
        sessionmaker=sessionmaker,
        redis=redis,
    )


@router.callback_query(MusicStyle.filter(), MusicGenerationState.style)
async def style_selected(
    query: CallbackQuery,
    callback_data: MusicStyle,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    await query.answer()

    style_key = callback_data.style
    if style_key == "custom":
        await edit_or_answer(
            query,
            text=MUSIC_STYLE_CUSTOM_TEXT,
            reply_markup=await ik_back_home(back_to=MusicBackTarget.TITLE),
        )
        return

    await update_music_data(state, style=style_key)
    await start_generation_from_style(
        query.message,
        state,
        user=user,
        session=session,
        sessionmaker=sessionmaker,
        redis=redis,
    )


async def start_generation_from_style(
    message: Message | None,
    state: FSMContext,
    *,
    user: UserRD,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    if message is None:
        return
    await start_generation(
        message,
        state,
        user=user,
        session=session,
        sessionmaker=sessionmaker,
        redis=redis,
    )


@router.callback_query(MusicStyle.filter(), MusicGenerationState.topic_style)
async def topic_style_selected(
    query: CallbackQuery,
    callback_data: MusicStyle,
    state: FSMContext,
) -> None:
    await query.answer()
    data = await get_music_data(state)

    style_key = callback_data.style
    if style_key == "custom":
        await edit_or_answer(
            query,
            text=(
                MUSIC_INSTRUMENTAL_STYLE_CUSTOM_TEXT
                if data.instrumental
                else music_topic_custom_style_text(data.topic)
            ),
            reply_markup=await ik_back_home(back_to=MusicBackTarget.TOPIC_STYLE),
        )
        return

    if data.instrumental:
        await update_music_data(state, style=style_key)
        await state.set_state(MusicGenerationState.prompt)
        await edit_or_answer(
            query,
            text=MUSIC_PROMPT_INSTRUMENTAL_TEXT,
            reply_markup=await ik_back_home(back_to=MusicBackTarget.TOPIC_STYLE),
        )
        return

    await update_music_data(state, style=style_key)
    await state.set_state(MusicGenerationState.topic_text_menu)
    await edit_or_answer(
        query,
        text=music_topic_text_menu_text(data.topic, style_key),
        reply_markup=await ik_music_topic_text_menu(),
    )


@router.message(MusicGenerationState.topic_style)
async def topic_style_custom_received(
    message: Message,
    state: FSMContext,
) -> None:
    style = (message.text or message.caption or "").strip()
    if not style and (message.voice or message.audio):
        try:
            style = await transcribe_message_audio(message, language="ru")
        except SpeechRecognitionError as err:
            logger.warning("Не удалось распознать аудио: %s", err)
            await message.answer(
                "Не удалось распознать аудио. Отправьте стиль текстом."
            )
            return
    if not style:
        await message.answer("Стиль не должен быть пустым.")
        return
    if len(style) > MAX_STYLE_LEN:
        await message.answer("Стиль слишком длинный. Укоротите до 1000 символов.")
        return

    data = await get_music_data(state)
    await update_music_data(state, style=style)
    if data.instrumental:
        await state.set_state(MusicGenerationState.prompt)
        await message.answer(
            MUSIC_PROMPT_INSTRUMENTAL_TEXT,
            reply_markup=await ik_back_home(back_to=MusicBackTarget.TOPIC_STYLE),
        )
        return
    await state.set_state(MusicGenerationState.topic_text_menu)
    await message.answer(
        music_topic_text_menu_text(data.topic, style),
        reply_markup=await ik_music_topic_text_menu(),
    )
