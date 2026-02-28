from __future__ import annotations

from urllib.parse import quote

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import select

from bot.db.enum import TransactionStatus, TransactionType
from bot.db.models import TransactionModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import ik_earn_menu
from bot.utils.messaging import edit_or_answer
from bot.utils.texts import earn_text

router = Router()


@router.callback_query(MenuAction.filter(F.action == "earn"))
async def menu_earn(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await query.answer()
    await state.clear()
    bot_name = (await query.bot.get_my_name()).name
    ref_link = await create_start_link(
        bot=query.bot,
        payload=f"ref_{user.user_id}",
        encode=False,
    )
    share_text = (
        "Приглашайте друзей и получайте 20% от всех их платежей в течение года!"
    )
    referrals_count = await session.scalar(
        select(func.count(UserModel.user_id)).where(
            UserModel.referrer_id == user.user_id
        )
    )
    referral_payments_count = await session.scalar(
        select(func.count(TransactionModel.id)).where(
            TransactionModel.user_idpk == user.id,
            TransactionModel.type == TransactionType.REFERRAL_BONUS.value,
            TransactionModel.status == TransactionStatus.SUCCESS.value,
        )
    )
    paid_kopeks = await session.scalar(
        select(func.coalesce(func.sum(TransactionModel.amount), 0)).where(
            TransactionModel.user_idpk == user.id,
            TransactionModel.type == TransactionType.WITHDRAW_REQUEST.value,
            TransactionModel.status == TransactionStatus.COMPLETED.value,
        )
    )
    payout_kopeks = await session.scalar(
        select(func.coalesce(func.sum(TransactionModel.amount), 0)).where(
            TransactionModel.user_idpk == user.id,
            TransactionModel.type == TransactionType.WITHDRAW_REQUEST.value,
            TransactionModel.status.in_(
                [
                    TransactionStatus.PENDING.value,
                    TransactionStatus.ASSIGNED.value,
                ]
            ),
        )
    )
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={quote(share_text)}"
    text = earn_text(
        bot_name=bot_name,
        referrals_count=referrals_count or 0,
        balance_kopeks=user.balance,
        paid_kopeks=int(paid_kopeks or 0),
        referral_payments_count=referral_payments_count or 0,
        payout_kopeks=int(payout_kopeks or 0),
        ref_link=ref_link,
    )
    await edit_or_answer(
        query,
        text=text,
        reply_markup=await ik_earn_menu(share_url=share_url),
    )
