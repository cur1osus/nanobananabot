from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.utils.payments import build_invoice
from bot.utils.texts import TEST_TOPUP_PLAN, get_topup_method, get_topup_tariff

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("testp"))
async def test_payment_cmd(message: Message, user: UserRD) -> None:
    """Тестовый платёж картой: 80 ₽ → 30 кредитов. Только для админа.

    Команда намеренно НЕ добавлена в публичный список команд бота, а тариф скрыт
    из меню пополнения. Платёж проходит через обычные pre_checkout/successful_payment,
    поэтому проверяет реальную работу шлюза и начисления кредитов.
    """
    if user.role != UserRole.ADMIN.value:
        await message.answer("У вас нет прав на выполнение этой команды.")
        return

    method_info = get_topup_method("card")
    tariff = get_topup_tariff("card", TEST_TOPUP_PLAN)
    if not method_info or not tariff:
        await message.answer("Тестовый тариф не настроен.")
        return

    invoice = build_invoice(method=method_info, tariff=tariff)
    if not invoice.provider_token:
        await message.answer(
            "Провайдер-токен ЮKassa не настроен — оплата картой недоступна."
        )
        return

    try:
        await message.answer_invoice(
            title="Тестовый платёж",
            description=f"Тестовое пополнение: {tariff.credits} кредитов за {tariff.price} ₽",
            payload=invoice.payload,
            provider_token=invoice.provider_token,
            currency=invoice.currency,
            prices=invoice.prices,
            provider_data=invoice.provider_data,
            need_email=invoice.need_email,
            send_email_to_provider=invoice.send_email_to_provider,
        )
    except TelegramBadRequest as err:
        logger.error(
            "Ошибка тестового sendInvoice: %s | provider_data=%s",
            err,
            invoice.provider_data,
        )
        await message.answer(
            "Не удалось создать тестовый счёт. Подробности в логах."
        )
