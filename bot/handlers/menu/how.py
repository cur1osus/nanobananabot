from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import ik_how_menu
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import how_text

router = Router()


@router.callback_query(MenuAction.filter(F.action == "how"))
async def menu_how(query: CallbackQuery) -> None:
    await query.answer()
    bot_name = (await query.bot.get_my_name()).name
    text = how_text(bot_name)
    await edit_or_answer(
        query,
        text=text,
        reply_markup=await ik_how_menu(),
    )
