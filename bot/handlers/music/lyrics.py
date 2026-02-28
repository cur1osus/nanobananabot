from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.enum import UsageEventType
from bot.db.func import charge_user_credits, refund_user_credits
from bot.db.redis.user_model import UserRD
from bot.keyboards.enums import MusicBackTarget
from bot.keyboards.factories import MusicTextAction, MusicTopic
from bot.keyboards.inline import (
    ik_back_home,
    ik_music_ai_result,
    ik_music_manual_prompt,
    ik_music_text_menu,
    ik_music_topic_styles,
)
from bot.states import MusicGenerationState
from bot.utils.agent_platform import AgentPlatformAPIError
from bot.utils.messaging import edit_or_answer
from bot.utils.music_helpers import _lyrics_client, ask_for_title  # noqa: PLC2701
from bot.utils.music_state import MusicFlowData, get_music_data, update_music_data
from bot.utils.music_topics import get_music_topic_label
from bot.utils.speech_recognition import (
    SpeechRecognitionError,
    transcribe_message_audio,
)
from bot.utils.texts import (
    LYRICS_MENU_TEXT,
    MUSIC_AI_EDIT_TEXT,
    MUSIC_TITLE_TEXT,
    music_ai_prompt_text,
    music_ai_result_text,
    music_instrumental_style_text,
    music_manual_prompt_text,
    music_topic_style_text,
)
from bot.utils.usage_events import record_usage_event

router = Router()
logger = logging.getLogger(__name__)
MAX_PROMPT_LEN = 1000
MAX_LYRICS_LEN = 5000


@router.callback_query(MusicTextAction.filter(F.action == "ai"))
async def lyrics_ai(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    data = await get_music_data(state)
    back_target = _text_menu_back_target(data)
    await state.set_state(MusicGenerationState.prompt)
    await update_music_data(
        state,
        prompt_source="ai",
        instrumental=False,
        custom_mode=True,
        prompt="",
        title="",
        style=data.style,
        topic=data.topic,
        prompt_after_mode=False,
        prompt_after_title=False,
    )
    prompt_text = music_ai_prompt_text()
    await edit_or_answer(
        query,
        text=prompt_text,
        reply_markup=await ik_back_home(back_to=back_target),
    )


@router.callback_query(MusicTopic.filter())
async def lyrics_topic(
    query: CallbackQuery,
    callback_data: MusicTopic,
    state: FSMContext,
) -> None:
    await query.answer()
    await state.set_state(MusicGenerationState.topic_style)
    await update_music_data(
        state,
        prompt_source=None,
        instrumental=False,
        custom_mode=True,
        prompt="",
        style="",
        title="",
        topic=callback_data.topic,
        prompt_after_mode=False,
        prompt_after_title=False,
    )
    await edit_or_answer(
        query,
        text=music_topic_style_text(callback_data.topic),
        reply_markup=await ik_music_topic_styles(),
    )


@router.callback_query(MusicTextAction.filter(F.action == "manual"))
async def lyrics_manual(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    data = await get_music_data(state)
    back_target = _text_menu_back_target(data)
    await state.set_state(MusicGenerationState.prompt)
    await update_music_data(
        state,
        prompt_source="manual",
        instrumental=False,
        custom_mode=True,
        prompt="",
        title="",
        style=data.style,
        topic=data.topic,
        prompt_after_mode=False,
        prompt_after_title=False,
    )
    prompt_text = music_manual_prompt_text()
    reply_markup = await ik_music_manual_prompt(back_to=back_target)
    await edit_or_answer(
        query,
        text=prompt_text,
        reply_markup=reply_markup,
    )


@router.callback_query(MusicTextAction.filter(F.action == "instrumental"))
async def lyrics_instrumental(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(MusicGenerationState.topic_style)
    await update_music_data(
        state,
        prompt_source="instrumental",
        instrumental=True,
        custom_mode=True,
        prompt="",
        title="",
        style="",
        topic="",
        prompt_after_mode=False,
        prompt_after_title=False,
    )
    await edit_or_answer(
        query,
        text=music_instrumental_style_text(),
        reply_markup=await ik_music_topic_styles(),
    )


@router.callback_query(MusicTextAction.filter(F.action == "ai_edit"))
async def lyrics_ai_edit(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    data = await get_music_data(state)
    if not data.prompt:
        await edit_or_answer(
            query,
            text="Нет текста для редактирования. Сначала сгенерируйте текст.",
            reply_markup=await ik_back_home(back_to=_text_menu_back_target(data)),
        )
        return
    await state.set_state(MusicGenerationState.prompt)
    await update_music_data(state, prompt_source="ai_edit")
    await edit_or_answer(
        query,
        text=MUSIC_AI_EDIT_TEXT,
        reply_markup=await ik_back_home(back_to=MusicBackTarget.AI_RESULT),
    )


@router.callback_query(MusicTextAction.filter(F.action == "generate_song"))
async def lyrics_generate_song(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    data = await get_music_data(state)
    if not data.prompt:
        await edit_or_answer(
            query,
            text="Нет текста для генерации песни. Сначала создай текст.",
            reply_markup=await ik_back_home(back_to=_text_menu_back_target(data)),
        )
        return
    await update_music_data(
        state,
        prompt_source="ai",
        title_back_target=MusicBackTarget.AI_RESULT.value,
    )
    await state.set_state(MusicGenerationState.title)
    await edit_or_answer(
        query,
        text=MUSIC_TITLE_TEXT,
        reply_markup=await ik_back_home(back_to=MusicBackTarget.AI_RESULT),
    )


@router.message(MusicGenerationState.prompt)
async def prompt_received(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    prompt = (message.text or message.caption or "").strip()
    if not prompt and (message.voice or message.audio):
        try:
            prompt = await transcribe_message_audio(message, language="ru")
        except SpeechRecognitionError as err:
            logger.warning("Не удалось распознать аудио: %s", err)
            await message.answer("Не удалось распознать аудио. Отправьте текстом.")
            return
    if not prompt:
        await message.answer("Текст не должен быть пустым.")
        return
    data = await get_music_data(state)
    back_target = _text_menu_back_target(data)
    if data.prompt_source == "manual" and len(prompt) > MAX_LYRICS_LEN:
        await message.answer("Текст песни слишком длинный. Укоротите до 5000 символов.")
        return
    if data.prompt_source != "manual" and len(prompt) > MAX_PROMPT_LEN:
        await message.answer("Промпт слишком длинный. Укоротите до 1000 символов.")
        return
    if data.prompt_source in {"ai", "ai_edit"}:
        if data.prompt_source == "ai_edit" and not data.prompt:
            await message.answer(
                "Нет текста для редактирования. Сначала сгенерируйте текст.",
                reply_markup=await ik_back_home(back_to=back_target),
            )
            return
        if data.prompt_source == "ai_edit":
            prompt_for_ai = _build_edit_prompt(data.prompt, prompt, data)
        else:
            prompt_for_ai = _attach_topic(prompt, data)
        if not await charge_user_credits(
            session=session,
            redis=redis,
            user=user,
            amount=1,
        ):
            await message.answer(
                "Недостаточно Hit$ для генерации текста.",
                reply_markup=await ik_back_home(back_to=back_target),
            )
            return
        await message.answer("Генерирую текст песни...")
        try:
            lyrics = await _lyrics_client().generate_song_text(prompt=prompt_for_ai)
        except AgentPlatformAPIError as err:
            logger.warning("Не удалось сгенерировать текст: %s", err)
            await refund_user_credits(
                session=session,
                redis=redis,
                user=user,
                amount=1,
            )
            await message.answer(
                "Не удалось сгенерировать текст песни. Попробуйте позже."
            )
            return

        await update_music_data(state, prompt=lyrics, prompt_source="ai")
        await record_usage_event(
            session=session,
            user_idpk=user.id,
            event_type=UsageEventType.AI_TEXT.value,
        )
        if data.topic and data.style:
            await state.set_state(MusicGenerationState.ai_result)
            text = music_ai_result_text(data.style, lyrics)
            await message.answer(
                text[:4000],
                reply_markup=await ik_music_ai_result(),
            )
            return
        preview = f"Текст песни:\n\n{lyrics}"
        await message.answer(preview[:4000])
    else:
        await update_music_data(state, prompt=prompt)
        if data.prompt_source == "manual":
            await record_usage_event(
                session=session,
                user_idpk=user.id,
                event_type=UsageEventType.MANUAL_TEXT.value,
            )

    if data.prompt_source == "instrumental":
        await ask_for_title(state, message, back_to=MusicBackTarget.PROMPT)
        return

    if data.prompt_source in {"ai", "ai_edit", "manual", "instrumental"}:
        await ask_for_title(state, message, back_to=MusicBackTarget.PROMPT)
        return

    await state.clear()
    await message.answer(
        text=LYRICS_MENU_TEXT,
        reply_markup=await ik_music_text_menu(),
    )


def _attach_topic(prompt: str, data: MusicFlowData) -> str:
    parts: list[str] = []
    topic_label = get_music_topic_label(data.topic)
    if topic_label:
        parts.append(f"Повод: {topic_label}")
    if data.style:
        parts.append(f"Жанр: {data.style}")
    if not parts:
        return prompt
    prefix = ". ".join(parts)
    if not prompt:
        return prefix
    return f"{prefix}. {prompt}"


def _build_edit_prompt(lyrics: str, instructions: str, data: MusicFlowData) -> str:
    base = _attach_topic("", data).strip()
    if base:
        base = f"{base}\n\n"
    return (
        f"{base}Отредактируй текст песни с учетом пожеланий.\n\n"
        f"Текст песни:\n{lyrics}\n\n"
        f"Пожелания:\n{instructions}"
    )


def _text_menu_back_target(data: MusicFlowData) -> MusicBackTarget:
    if data.topic and data.style:
        return MusicBackTarget.TOPIC_TEXT_MENU
    return MusicBackTarget.TEXT_MENU
