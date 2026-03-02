from typing import Final

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.factories import (
    InfoPeriod,
    MenuAction,
    ModelMenu,
    ModelSelect,
    TopupMethod,
    TopupPlan,
    WithdrawAction,
)
from bot.utils.image_models import IMAGE_MODELS, DEFAULT_IMAGE_MODEL_KEY
from bot.utils.texts import get_topup_method, get_topup_tariffs

LIMIT_BUTTONS: Final[int] = 100
BACK_BUTTON_TEXT = "🔙 Назад"


def _model_button_label(model_key: str, selected_key: str) -> str:
    for option in IMAGE_MODELS:
        if option.key == model_key:
            label = option.button_label
            break
    else:
        label = IMAGE_MODELS[0].button_label
    if model_key == selected_key:
        return f"✅ {label}"
    return label


async def ik_choose_model() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🍌 Выбрать модель", callback_data=ModelMenu().pack())
    builder.adjust(1)
    return builder.as_markup()


async def ik_image_model_select(
    selected_key: str = DEFAULT_IMAGE_MODEL_KEY,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in IMAGE_MODELS:
        builder.button(
            text=_model_button_label(option.key, selected_key),
            callback_data=ModelSelect(model=option.key).pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


async def ik_image_waiting_photos() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔙 К выбору модели",
        callback_data=ModelMenu().pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_main(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🍌 Создать изображение",
        callback_data=MenuAction(action="image").pack(),
    )
    builder.button(
        text="ℹ️ Как это работает?",
        callback_data=MenuAction(action="how").pack(),
    )
    builder.button(
        text="💳 Пополнить баланс",
        callback_data=MenuAction(action="topup").pack(),
    )
    builder.button(
        text="🪙 Заработать",
        callback_data=MenuAction(action="earn").pack(),
    )
    builder.button(
        text="📞 Контакты",
        callback_data=MenuAction(action="contacts").pack(),
    )
    if is_admin:
        builder.button(
            text="АдминПанель",
            callback_data=MenuAction(action="info").pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


async def ik_how_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🍌 Создать изображение",
        callback_data=MenuAction(action="image").pack(),
    )
    builder.button(
        text="💳 Пополнить баланс",
        callback_data=MenuAction(action="topup").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_topup_methods() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⭐️ Звезды",
        callback_data=TopupMethod(method="stars").pack(),
    )
    builder.button(
        text="💳 Банковская карта",
        callback_data=TopupMethod(method="card").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_topup_plans(method: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    method_info = get_topup_method(method)
    tariffs = get_topup_tariffs(method)
    currency_label = method_info.currency_label if method_info else "руб."
    for tariff in tariffs:
        builder.button(
            text=(f"{tariff.credits} генераций - {tariff.price} {currency_label}"),
            callback_data=TopupPlan(method=method, plan=tariff.plan).pack(),
        )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="topup").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_earn_menu(share_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📤 Поделиться",
        url=share_url,
    )
    builder.button(
        text="🪙 Запросить вывод",
        callback_data=MenuAction(action="withdraw").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_back_earn() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="earn").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_back_withdraw() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="withdraw").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_withdraw_manager(transaction_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Завершено",
        callback_data=WithdrawAction(
            action="done", transaction_id=transaction_id
        ).pack(),
    )
    builder.button(
        text="⚠️ Ошибка",
        callback_data=WithdrawAction(
            action="error", transaction_id=transaction_id
        ).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_withdraw_cancel(transaction_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Отмена",
        callback_data=WithdrawAction(
            action="cancel", transaction_id=transaction_id
        ).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_info_periods(selected: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    periods = [("day", "День"), ("week", "Неделя"), ("month", "Месяц")]
    for key, label in periods:
        prefix = "✅ " if key == selected else ""
        builder.button(
            text=f"{prefix}{label}",
            callback_data=InfoPeriod(period=key).pack(),
        )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(3, 1)
    return builder.as_markup()


async def ik_back_home() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()
