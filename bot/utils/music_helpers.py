from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

from bot.background_tasks import MIN_POLL_TIMEOUT
from bot.db.enum import MusicTaskStatus, UsageEventType, UserRole
from bot.db.func import charge_user_credits, refund_user_credits
from bot.db.models import MusicTaskModel, UserModel
from bot.keyboards.enums import MusicBackTarget
from bot.keyboards.inline import ik_back_home, ik_main, ik_no_credits
from bot.states import MusicGenerationState
from bot.utils.agent_platform import build_agent_platform_client
from bot.utils.music_state import get_music_data, update_music_data
from bot.utils.suno_api import SunoAPIError, build_suno_client
from bot.utils.texts import (
    MUSIC_NO_CREDITS_TEXT,
    MUSIC_TITLE_TEXT,
    music_generation_started_text,
    music_instrumental_title_text,
)
from bot.utils.usage_events import record_usage_event

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from bot.db.redis.user_model import UserRD
    from bot.utils.agent_platform import AgentPlatformClient
    from bot.utils.suno_api import SunoClient


logger = logging.getLogger(__name__)

SECTION_LINE_RE = re.compile(
    r"^\s*[\[\(\{]?\s*"
    r"(?:куплет|припев|бридж|мост|интро|аутро|проигрыш|кода|финал"
    r"|verse|chorus|bridge|intro|outro|pre\s*chorus|hook|refrain)"
    r"\s*(?:\d+|[ivx]+)?\s*[\]\)\}]?\s*[:\-–—]?\s*$",
    re.IGNORECASE,
)


def _client() -> SunoClient:
    return build_suno_client()


def _lyrics_client() -> AgentPlatformClient:
    return build_agent_platform_client()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if SECTION_LINE_RE.match(stripped):
            continue
        return stripped
    return ""


async def ask_for_title(
    state: FSMContext,
    message: Message,
    *,
    back_to: MusicBackTarget = MusicBackTarget.PROMPT,
) -> None:
    await update_music_data(state, title_back_target=back_to.value)
    data = await get_music_data(state)
    text = (
        music_instrumental_title_text(data.style)
        if data.instrumental
        else MUSIC_TITLE_TEXT
    )
    await state.set_state(MusicGenerationState.title)
    await message.answer(
        text,
        reply_markup=await ik_back_home(back_to=back_to),
    )


async def start_generation(
    message: Message,
    state: FSMContext,
    *,
    user: UserRD,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    client = _client()
    data = await get_music_data(state)
    custom_mode = data.custom_mode
    instrumental = data.instrumental
    prompt = data.prompt
    generation_prompt = prompt
    style = data.style if custom_mode else ""
    title = data.title if custom_mode else ""

    if not custom_mode:
        await update_music_data(state, custom_mode=True)
        custom_mode = True

    if not generation_prompt:
        await message.answer("Промпт не задан.")
        return

    credits_cost = 2
    if not await charge_user_credits(
        session=session,
        redis=redis,
        user=user,
        amount=credits_cost,
    ):
        await message.answer(
            MUSIC_NO_CREDITS_TEXT,
            reply_markup=await ik_no_credits(back_to=MusicBackTarget.TITLE),
        )
        return

    await state.set_state(MusicGenerationState.waiting)

    try:
        task_id = await client.generate_music(
            prompt=generation_prompt,
            custom_mode=custom_mode,
            instrumental=instrumental,
            style=style,
            title=title,
        )
    except SunoAPIError as err:
        logger.warning("Не удалось запустить генерацию музыки: %s", err)
        await refund_user_credits(
            session=session,
            redis=redis,
            user=user,
            amount=credits_cost,
        )
        await message.answer("Не удалось запустить генерацию музыки. Попробуйте позже.")
        await state.clear()
        return

    if instrumental:
        await record_usage_event(
            session=session,
            user_idpk=user.id,
            event_type=UsageEventType.INSTRUMENTAL.value,
        )

    base_name = title.strip() if title.strip() else _first_line(prompt)
    if not base_name:
        base_name = "Трек"

    user_db = await session.scalar(
        select(UserModel).where(UserModel.user_id == user.user_id)
    )
    if not user_db:
        await refund_user_credits(
            session=session,
            redis=redis,
            user=user,
            amount=credits_cost,
        )
        await message.answer("Не удалось сохранить задачу генерации. Попробуйте позже.")
        await state.clear()
        return

    music_task = MusicTaskModel(
        user_idpk=user_db.id,
        task_id=task_id,
        chat_id=message.chat.id,
        filename_base=base_name,
        status=MusicTaskStatus.PENDING.value,
        errors=0,
        credits_cost=credits_cost,
        poll_timeout=max(client.poll_timeout, MIN_POLL_TIMEOUT),
        topic_key=data.topic or None,
        style=data.style.strip() or None,
        prompt_source=data.prompt_source or None,
        prompt=data.prompt or None,
        custom_mode=custom_mode,
        instrumental=instrumental,
    )
    try:
        session.add(music_task)
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось сохранить задачу генерации: %s", err)
        await refund_user_credits(
            session=session,
            redis=redis,
            user=user,
            amount=credits_cost,
        )
        await message.answer("Не удалось сохранить задачу генерации. Попробуйте позже.")
        await state.clear()
        return

    text = music_generation_started_text(task_id, base_name)
    await message.answer(
        text,
        reply_markup=await ik_main(is_admin=user.role == UserRole.ADMIN.value),
    )
    await state.clear()
