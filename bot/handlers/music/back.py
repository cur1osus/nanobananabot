from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.keyboards.enums import MusicBackTarget
from bot.keyboards.factories import MusicBack
from bot.keyboards.inline import (
    ik_back_home,
    ik_main,
    ik_music_ai_result,
    ik_music_styles,
    ik_music_text_menu,
    ik_music_topic_styles,
    ik_music_topic_text_menu,
)
from bot.states import BaseUserState, MusicGenerationState
from bot.utils.messaging import edit_or_answer
from bot.utils.music_state import MusicFlowData, get_music_data
from bot.utils.texts import (
    LYRICS_MENU_TEXT,
    MUSIC_PROMPT_INSTRUMENTAL_TEXT,
    MUSIC_PROMPT_TEXT,
    MUSIC_STYLE_TEXT,
    MUSIC_TITLE_TEXT,
    main_menu_text,
    music_ai_prompt_text,
    music_ai_result_text,
    music_instrumental_style_text,
    music_manual_prompt_text,
    music_topic_style_text,
    music_topic_text_menu_text,
)

router = Router()


@router.callback_query(MusicBack.filter())
async def music_back(
    query: CallbackQuery,
    callback_data: MusicBack,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    target = MusicBackTarget(callback_data.target)

    if target == MusicBackTarget.HOME:
        await state.set_state(BaseUserState.main)
        await edit_or_answer(
            query,
            text=main_menu_text(user),
            reply_markup=await ik_main(is_admin=user.role == UserRole.ADMIN.value),
        )
    elif target == MusicBackTarget.TEXT_MENU:
        await state.clear()
        await edit_or_answer(
            query,
            text=LYRICS_MENU_TEXT,
            reply_markup=await ik_music_text_menu(),
        )
    elif target == MusicBackTarget.MODE:
        data = await get_music_data(state)
        await state.set_state(MusicGenerationState.prompt)
        await edit_or_answer(
            query,
            text=_prompt_text(data),
            reply_markup=await ik_back_home(back_to=MusicBackTarget.TEXT_MENU),
        )
    elif target == MusicBackTarget.STYLE:
        await state.set_state(MusicGenerationState.style)
        await edit_or_answer(
            query,
            text=MUSIC_STYLE_TEXT,
            reply_markup=await ik_music_styles(),
        )
    elif target == MusicBackTarget.TITLE:
        data = await get_music_data(state)
        back_target = _title_back_target(data)
        await state.set_state(MusicGenerationState.title)
        await edit_or_answer(
            query,
            text=MUSIC_TITLE_TEXT,
            reply_markup=await ik_back_home(back_to=back_target),
        )
    elif target == MusicBackTarget.PROMPT:
        data = await get_music_data(state)
        if data.instrumental:
            back_target = MusicBackTarget.TOPIC_STYLE
        else:
            back_target = (
                MusicBackTarget.TOPIC_TEXT_MENU
                if data.topic and data.style
                else MusicBackTarget.TEXT_MENU
            )
        await state.set_state(MusicGenerationState.prompt)
        await edit_or_answer(
            query,
            text=_prompt_text(data),
            reply_markup=await ik_back_home(back_to=back_target),
        )
    elif target == MusicBackTarget.TOPIC_STYLE:
        data = await get_music_data(state)
        await state.set_state(MusicGenerationState.topic_style)
        await edit_or_answer(
            query,
            text=(
                music_instrumental_style_text()
                if data.instrumental
                else music_topic_style_text(data.topic)
            ),
            reply_markup=await ik_music_topic_styles(),
        )
    elif target == MusicBackTarget.TOPIC_TEXT_MENU:
        data = await get_music_data(state)
        await state.set_state(MusicGenerationState.topic_text_menu)
        await edit_or_answer(
            query,
            text=music_topic_text_menu_text(data.topic, data.style),
            reply_markup=await ik_music_topic_text_menu(),
        )
    elif target == MusicBackTarget.AI_RESULT:
        data = await get_music_data(state)
        if not data.prompt:
            if data.topic and data.style:
                await state.set_state(MusicGenerationState.topic_text_menu)
                await edit_or_answer(
                    query,
                    text=music_topic_text_menu_text(data.topic, data.style),
                    reply_markup=await ik_music_topic_text_menu(),
                )
            else:
                await state.clear()
                await edit_or_answer(
                    query,
                    text=LYRICS_MENU_TEXT,
                    reply_markup=await ik_music_text_menu(),
                )
            return
        await state.set_state(MusicGenerationState.ai_result)
        text = music_ai_result_text(data.style, data.prompt)
        await edit_or_answer(
            query,
            text=text[:4000],
            reply_markup=await ik_music_ai_result(),
        )


def _prompt_text(data: MusicFlowData) -> str:
    if data.prompt_source in {"ai", "ai_edit"}:
        return music_ai_prompt_text()
    if data.prompt_source == "manual":
        return music_manual_prompt_text()
    if data.prompt_source == "instrumental":
        return MUSIC_PROMPT_INSTRUMENTAL_TEXT
    return MUSIC_PROMPT_TEXT


def _title_back_target(data: MusicFlowData) -> MusicBackTarget:
    raw_target = data.title_back_target
    if raw_target:
        try:
            return MusicBackTarget(raw_target)
        except ValueError:
            return MusicBackTarget.PROMPT
    if data.topic and data.style:
        return MusicBackTarget.AI_RESULT
    return MusicBackTarget.PROMPT
