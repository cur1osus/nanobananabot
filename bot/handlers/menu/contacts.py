from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.factories import MenuAction
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import CONTACTS_TEXT

router = Router()


async def ik_contacts_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔙 Назад",
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(MenuAction.filter(F.action == "contacts"))
async def menu_contacts(query: CallbackQuery) -> None:
    await query.answer()
    await edit_or_answer(
        query,
        text=CONTACTS_TEXT,
        reply_markup=await ik_contacts_menu(),
    )
