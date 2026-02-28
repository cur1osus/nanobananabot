from __future__ import annotations

import json
from dataclasses import dataclass

from aiogram.types import LabeledPrice

from bot.settings import se
from bot.utils.texts import TopupMethodInfo, TopupTariff

PAYLOAD_PREFIX = "topup"
STARS_CURRENCY = "XTR"
CARD_CURRENCY = "RUB"


@dataclass(frozen=True)
class InvoiceConfig:
    title: str
    description: str
    payload: str
    currency: str
    prices: list[LabeledPrice]
    provider_token: str
    provider_data: str | None
    need_email: bool
    send_email_to_provider: bool


def _receipt_amount_value(price_rub: int) -> str:
    return f"{price_rub:.2f}"


def build_yookassa_provider_data(*, tariff: TopupTariff) -> str:
    item = {
        "description": f"Пополнение: {tariff.credits} Hit$",
        "quantity": 1,
        "amount": {
            "value": _receipt_amount_value(tariff.price),
            "currency": CARD_CURRENCY,
        },
        "vat_code": se.payments.yookassa_vat_code,
        "payment_mode": se.payments.yookassa_payment_mode,
        "payment_subject": se.payments.yookassa_payment_subject,
    }
    provider_data = {
        "receipt": {
            "items": [item],
            "tax_system_code": se.payments.yookassa_tax_system_code,
        }
    }
    return json.dumps(provider_data, ensure_ascii=True)


def build_payload(method: str, plan: str) -> str:
    return f"{PAYLOAD_PREFIX}:{method}:{plan}"


def parse_payload(payload: str) -> tuple[str, str] | None:
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX:
        return None
    _, method, plan = parts
    return method, plan


def build_invoice(
    *,
    method: TopupMethodInfo,
    tariff: TopupTariff,
) -> InvoiceConfig:
    title = f"Пополнение: {tariff.credits} Hit$"
    description = f"{tariff.credits} Hit$ ({tariff.songs} генераций песен)"
    payload = build_payload(method.key, tariff.plan)
    if method.key == "stars":
        currency = STARS_CURRENCY
        provider_token = ""
        amount = tariff.price
        provider_data = None
        need_email = False
        send_email_to_provider = False
    else:
        currency = CARD_CURRENCY
        provider_token = se.payments.yookassa_provider_token
        amount = tariff.price * 100
        provider_data = build_yookassa_provider_data(tariff=tariff)
        need_email = True
        send_email_to_provider = True

    prices = [LabeledPrice(label=title, amount=amount)]
    return InvoiceConfig(
        title=title,
        description=description,
        payload=payload,
        currency=currency,
        prices=prices,
        provider_token=provider_token,
        provider_data=provider_data,
        need_email=need_email,
        send_email_to_provider=send_email_to_provider,
    )
