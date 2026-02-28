from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import ik_music_text_menu
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import LYRICS_MENU_TEXT

router = Router()


@router.callback_query(MenuAction.filter(F.action == "music"))
async def music_entry(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.clear()
    await edit_or_answer(
        query,
        text=LYRICS_MENU_TEXT,
        reply_markup=await ik_music_text_menu(),
    )
