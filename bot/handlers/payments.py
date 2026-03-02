from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery, SuccessfulPayment
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import TransactionStatus, TransactionType
from bot.db.func import add_referral_balance, add_user_credits
from bot.db.models import TransactionModel, UserModel
from bot.db.redis.user_model import UserRD
from bot.utils.payments import CARD_CURRENCY, STARS_CURRENCY, parse_payload
from bot.utils.texts import get_topup_method, get_topup_tariff

router = Router()
logger = logging.getLogger(__name__)


@router.pre_checkout_query()
async def pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    parsed = parse_payload(pre_checkout.invoice_payload)
    if not parsed:
        logger.warning(
            "Некорректные данные предпроверки платежа: %s",
            pre_checkout.invoice_payload,
        )
        await pre_checkout.answer(ok=False, error_message="Неверные данные платежа.")
        return

    method, plan = parsed
    method_info = get_topup_method(method)
    tariff = get_topup_tariff(method, plan)
    if not method_info or not tariff:
        logger.warning(
            "Неизвестный тариф предпроверки платежа: способ=%s тариф=%s",
            method,
            plan,
        )
        await pre_checkout.answer(ok=False, error_message="Тариф не найден.")
        return

    expected_amount = tariff.price if method == "stars" else tariff.price * 100
    expected_currency = STARS_CURRENCY if method == "stars" else CARD_CURRENCY
    if (
        pre_checkout.total_amount != expected_amount
        or pre_checkout.currency != expected_currency
    ):
        logger.warning(
            "Несовпадение предпроверки платежа: данные=%s сумма=%s валюта=%s",
            pre_checkout.invoice_payload,
            pre_checkout.total_amount,
            pre_checkout.currency,
        )
        await pre_checkout.answer(ok=False, error_message="Сумма платежа не совпадает.")
        return

    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(
    message: Message,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    payment = message.successful_payment
    if not payment:
        return

    parsed = parse_payload(payment.invoice_payload)
    if not parsed:
        logger.warning("Неизвестные данные платежа: %s", payment.invoice_payload)
        await message.answer("Не удалось определить тариф. Напишите в поддержку.")
        return

    method, plan = parsed
    tariff = get_topup_tariff(method, plan)
    if not tariff:
        logger.warning("Неизвестный тариф для платежа: %s", payment.invoice_payload)
        await message.answer("Тариф не найден. Напишите в поддержку.")
        return

    expected_amount = tariff.price if method == "stars" else tariff.price * 100
    expected_currency = STARS_CURRENCY if method == "stars" else CARD_CURRENCY
    if payment.total_amount != expected_amount or payment.currency != expected_currency:
        logger.warning(
            "Несовпадение платежа: данные=%s, сумма=%s, валюта=%s",
            payment.invoice_payload,
            payment.total_amount,
            payment.currency,
        )
        await message.answer(
            "Сумма платежа не совпадает с актуальными тарифами. Зайдите в пополнение и выберите подходящий тариф."
        )
        return

    await add_user_credits(
        session=session,
        redis=redis,
        user=user,
        amount=tariff.credits,
    )

    transaction = TransactionModel(
        user_idpk=user.id,
        type=TransactionType.TOPUP.value,
        method=method,
        plan=plan,
        amount=payment.total_amount,
        currency=payment.currency,
        credits=tariff.credits,
        status=TransactionStatus.SUCCESS.value,
        payload=payment.invoice_payload,
        telegram_charge_id=payment.telegram_payment_charge_id or None,
        provider_charge_id=payment.provider_payment_charge_id or None,
    )
    try:
        session.add(transaction)
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось сохранить транзакцию: %s", err)
        await message.answer(
            "Оплата прошла, кредиты начислены, но транзакция не сохранена. "
            "Напишите в поддержку."
        )
        return

    await _apply_referral_bonus(
        session=session,
        redis=redis,
        user=user,
        method=method,
        plan=plan,
        payment=payment,
    )

    await message.answer(f"Оплата прошла успешно! Начислено {tariff.credits} кредитов.")


async def _apply_referral_bonus(
    *,
    session: AsyncSession,
    redis: Redis,
    user: UserRD,
    method: str,
    plan: str,
    payment: SuccessfulPayment,
) -> None:
    if not user.referrer_id:
        return

    referrer_db = await session.scalar(
        select(UserModel).where(UserModel.user_id == user.referrer_id)
    )
    if not referrer_db:
        logger.warning(
            "Не найден реферер для начисления бонуса: рефер=%s",
            user.referrer_id,
        )
        return

    base_amount = (
        payment.total_amount * 100
        if payment.currency == STARS_CURRENCY
        else payment.total_amount
    )
    bonus = base_amount // 5
    if bonus <= 0:
        return

    applied = await add_referral_balance(
        session=session,
        redis=redis,
        referrer_id=user.referrer_id,
        amount=bonus,
    )
    if not applied:
        logger.warning(
            "Не удалось начислить реферальный бонус: рефер=%s сумма=%s",
            user.referrer_id,
            bonus,
        )
        return

    bonus_transaction = TransactionModel(
        user_idpk=referrer_db.id,
        type=TransactionType.REFERRAL_BONUS.value,
        method=method,
        plan=plan,
        amount=bonus,
        currency=CARD_CURRENCY,
        credits=0,
        status=TransactionStatus.SUCCESS.value,
        payload=payment.invoice_payload,
        details=f"Бонус за оплату пользователя {user.user_id}",
    )
    try:
        session.add(bonus_transaction)
        await session.commit()
    except Exception as err:
        await session.rollback()
        logger.warning("Не удалось сохранить реферальную транзакцию: %s", err)
