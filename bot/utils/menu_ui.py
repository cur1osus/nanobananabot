from __future__ import annotations

from aiogram.types import Message

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.keyboards.inline import ik_main
from bot.utils.texts import main_menu_text


async def send_main_menu(message: Message, user: UserRD) -> None:
    await message.answer(
        text=main_menu_text(user),
        reply_markup=await ik_main(is_admin=user.role == UserRole.ADMIN.value),
    )
