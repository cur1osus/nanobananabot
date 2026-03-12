from __future__ import annotations

from urllib.parse import quote

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import select

from bot.db.enum import TransactionStatus, TransactionType
from bot.db.models import TransactionModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.inline import (
    ik_earn_menu,
    ik_how_menu,
    ik_image_model_select,
    ik_topup_methods,
)
from bot.states import ImageGenerationState
from bot.utils.image_models import DEFAULT_IMAGE_MODEL_KEY
from bot.utils.image_state import get_image_data, update_image_data
from bot.utils.texts import (
    CONTACTS_TEXT,
    PROMPT_EXAMPLES_TEXT,
    TOPUP_METHODS_TEXT,
    earn_text,
    how_text,
    model_panel_text,
)

router = Router()


@router.message(Command("gen"))
async def cmd_gen(message: Message, state: FSMContext, user: UserRD) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await state.clear()
    await update_image_data(
        state,
        model_key=selected_key,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    await message.answer(
        model_panel_text(user, selected_key),
        reply_markup=await ik_image_model_select(selected_key),
    )


@router.message(Command("create"))
async def cmd_create(message: Message, state: FSMContext, user: UserRD) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await state.clear()
    await update_image_data(
        state,
        model_key=selected_key,
        photos=[],
        prompt="",
        prompt_requested=False,
        aspect_ratio="auto",
    )
    await state.set_state(ImageGenerationState.waiting_create_model)
    await message.answer(
        model_panel_text(user, selected_key),
        reply_markup=await ik_image_model_select(selected_key),
    )


@router.message(Command("model"))
async def cmd_model(message: Message, state: FSMContext, user: UserRD) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await message.answer(
        model_panel_text(user, selected_key),
        reply_markup=await ik_image_model_select(selected_key),
    )


@router.message(Command("buy"))
async def cmd_buy(message: Message) -> None:
    await message.answer(TOPUP_METHODS_TEXT, reply_markup=await ik_topup_methods())


@router.message(Command("example"))
async def cmd_example(message: Message) -> None:
    await message.answer(PROMPT_EXAMPLES_TEXT)


@router.message(Command("friend"))
async def cmd_friend(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await state.clear()
    bot = message.bot
    if bot is None:
        return
    assert bot is not None

    bot_name = (await bot.get_my_name()).name
    ref_link = await create_start_link(
        bot=bot,
        payload=f"ref_{user.user_id}",
        encode=False,
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
    text = earn_text(
        bot_name=bot_name,
        referrals_count=referrals_count or 0,
        balance_kopeks=user.balance,
        paid_kopeks=int(paid_kopeks or 0),
        referral_payments_count=referral_payments_count or 0,
        payout_kopeks=int(payout_kopeks or 0),
        ref_link=ref_link,
    )
    share_text = (
        "Приглашайте друзей и получайте 20% от всех их платежей в течение года!"
    )
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={quote(share_text)}"
    await message.answer(
        text,
        reply_markup=await ik_earn_menu(share_url=share_url),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    bot = message.bot
    if bot is None:
        return
    assert bot is not None

    bot_name = (await bot.get_my_name()).name
    await message.answer(how_text(bot_name), reply_markup=await ik_how_menu())
    await message.answer(CONTACTS_TEXT)
