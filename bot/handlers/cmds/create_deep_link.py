from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters.command import Command
from aiogram.utils.deep_linking import create_start_link

if TYPE_CHECKING:
    from aiogram.types import Message


router = Router()


@router.message(Command(commands=["ad"]))
async def add_new_bot(message: Message) -> None:
    await message.answer(await create_start_link(bot=message.bot, payload="start"))  # pyright: ignore
