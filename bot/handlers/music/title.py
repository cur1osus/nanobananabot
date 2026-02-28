from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.redis.user_model import UserRD
from bot.keyboards.inline import ik_music_styles
from bot.states import MusicGenerationState
from bot.utils.music_helpers import start_generation
from bot.utils.music_state import get_music_data, update_music_data
from bot.utils.texts import MUSIC_STYLE_TEXT

router = Router()
MAX_TITLE_LEN = 100


@router.message(MusicGenerationState.title)
async def title_received(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым.")
        return
    if len(title) > MAX_TITLE_LEN:
        await message.answer("Название слишком длинное. Укоротите до 100 символов.")
        return

    await update_music_data(state, title=title, custom_mode=True)
    data = await get_music_data(state)
    if data.instrumental or (data.topic and data.style):
        await start_generation(
            message,
            state,
            user=user,
            session=session,
            sessionmaker=sessionmaker,
            redis=redis,
        )
        return

    await state.set_state(MusicGenerationState.style)
    await message.answer(
        MUSIC_STYLE_TEXT,
        reply_markup=await ik_music_styles(),
    )
