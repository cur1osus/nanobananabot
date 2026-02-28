from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.factories import MenuAction, TopupMethod, TopupPlan
from bot.keyboards.inline import ik_topup_methods, ik_topup_plans
from bot.utils.messaging import edit_or_answer
from bot.utils.payments import build_invoice
from bot.utils.texts import (
    TOPUP_METHODS_TEXT,
    get_topup_method,
    get_topup_tariff,
    topup_tariffs_text,
)

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(MenuAction.filter(F.action == "topup"))
async def menu_topup(query: CallbackQuery) -> None:
    await query.answer()
    await edit_or_answer(
        query,
        text=TOPUP_METHODS_TEXT,
        reply_markup=await ik_topup_methods(),
    )


@router.callback_query(TopupMethod.filter())
async def topup_method(query: CallbackQuery, callback_data: TopupMethod) -> None:
    await query.answer()
    text = topup_tariffs_text(callback_data.method)
    await edit_or_answer(
        query,
        text=text,
        reply_markup=await ik_topup_plans(callback_data.method),
    )


@router.callback_query(TopupPlan.filter())
async def topup_plan(query: CallbackQuery, callback_data: TopupPlan) -> None:
    await query.answer()
    method_info = get_topup_method(callback_data.method)
    tariff = get_topup_tariff(callback_data.method, callback_data.plan)
    if not method_info or not tariff:
        logger.warning(
            "Не найден тариф пополнения: способ=%s тариф=%s",
            callback_data.method,
            callback_data.plan,
        )
        await query.message.answer(
            "Не удалось определить тариф. Попробуйте снова через меню пополнения."
        )
        return

    invoice = build_invoice(method=method_info, tariff=tariff)
    if method_info.key == "card" and not invoice.provider_token:
        logger.warning("Провайдер-токен ЮKassa не настроен")
        await query.message.answer(
            "Оплата картой временно недоступна. Попробуйте позже."
        )
        return
    await query.message.answer_invoice(
        title=invoice.title,
        description=invoice.description,
        payload=invoice.payload,
        provider_token=invoice.provider_token,
        currency=invoice.currency,
        prices=invoice.prices,
        provider_data=invoice.provider_data,
        need_email=invoice.need_email,
        send_email_to_provider=invoice.send_email_to_provider,
    )
