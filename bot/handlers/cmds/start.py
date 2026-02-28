from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart

from bot.db.redis.user_model import UserRD
from bot.keyboards.inline import ik_choose_model
from bot.utils.referrals import apply_referral
from bot.utils.texts import nanobanana_welcome_text

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from aiogram.types import Message
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession


router = Router()


@router.message(CommandStart(deep_link=True))
async def start_cmd_with_deep_link(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: UserRD,
    redis: Redis,
    state: FSMContext,
) -> None:
    await state.clear()
    args = command.args.split() if command.args else []
    deep_link = args[0] if args else ""
    applied = False
    if deep_link and user:
        applied = await apply_referral(
            session=session,
            redis=redis,
            user=user,
            payload=deep_link,
        )
    if applied:
        await message.answer("Ты воспользовался реферальной ссылкой!")
    await message.answer(
        nanobanana_welcome_text(),
        reply_markup=await ik_choose_model(),
    )


@router.message(CommandStart(deep_link=False))
async def start_cmd(
    message: Message,
    user: UserRD,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer(
        nanobanana_welcome_text(),
        reply_markup=await ik_choose_model(),
    )
