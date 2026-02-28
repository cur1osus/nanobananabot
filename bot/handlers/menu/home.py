from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import ik_main
from bot.states import BaseUserState
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import main_menu_text

router = Router()


@router.callback_query(MenuAction.filter(F.action == "home"))
async def menu_home(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    await state.set_state(BaseUserState.main)
    await edit_or_answer(
        query,
        text=main_menu_text(user),
        reply_markup=await ik_main(is_admin=user.role == UserRole.ADMIN.value),
    )
