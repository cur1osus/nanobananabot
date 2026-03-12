from __future__ import annotations

import logging
from dataclasses import dataclass

from bot.db.redis.user_model import UserRD
from bot.settings import se
from bot.utils.formatting import format_rub

MAIN_MENU_TEXT = (
    "🏠 Главное меню\n💰 Ваш баланс: {credits} кредитов\n🖼 Что вы хотите сделать?"
)

BOT_INFO_TEXT = (
    "Bum Ai Bot 🤖 — редактирование и генерация изображений.\n\n"
    "Поддержка: @NanoBanana_support"
)

CONTACTS_TEXT = (
    "📞 Контакты\n\n"
    "Служба поддержки: @NanoBanana_support\n"
    "Официальный канал: @NanoBanana_official\n"
    "Чат: @NanoBanana_chat"
)


BOT_DESCRIPTION_TEXT = (
    "🤖 Добро пожаловать в Bum Ai Bot!\n\n"
    "Что умеет бот:\n"
    "• 🖌 Редактирование фото (1–8 фото в зависимости от модели)\n"
    "• ✨ Генерация изображений по текстовому описанию\n"
    "• 🎙 Поддержка голосового ввода промпта\n\n"
    "Как начать:\n"
    "1) Нажмите /start\n"
    "2) Выберите «Редактирование фото» или «Генерация изображения»\n"
    "3) Следуйте подсказкам бота\n\n"
    "Поддержка: @NanoBanana_support"
)

NANOBANANA_WELCOME_TEXT = (
    "🍌 Добро пожаловать в Nano Banana!\n\n"
    "У тебя 5 бесплатных генераций.\n\n"
    "Модели:\n{models}\n\n"
    "Нажми кнопку ниже, чтобы выбрать модель."
)

PHOTO_REQUEST_TEXT = "Пришлите 1-4 фотографии которые нужно изменить или объединить"

PROMPT_REQUEST_TEXT = (
    "Теперь опишите, что нужно изменить.\n"
    "Например: «Сделай фон закатным, добавь мягкий свет и киношные цвета».\n\n"
    "💡 Можно ввести текстом или продиктовать голосом"
)

PROMPT_EXAMPLES_TEXT = (
    "💡 Примеры промптов:\n\n"
    "1) Сделай фон красным, человека не меняй.\n"
    "2) Замени фон на офис, сохрани одежду и позу.\n"
    "3) Сделай фото в стиле кинокадра, мягкий теплый свет.\n"
    "4) Убери лишние объекты с заднего плана.\n"
    "5) Улучши качество и резкость, без изменения лица."
)

CREATE_ASPECT_RATIO_TEXT = (
    "✨ Режим создания изображения\n\nСначала выберите соотношение сторон:"
)

CREATE_PROMPT_TEXT = (
    "Отлично. Теперь опишите, что сгенерировать.\n"
    "Например: «Красный спорткар на ночной улице в дождь, неон, кинокадр»."
)


def nanobanana_welcome_text() -> str:
    from bot.utils.image_models import IMAGE_MODELS, model_bullet_line

    models = "\n".join(model_bullet_line(option) for option in IMAGE_MODELS)
    return NANOBANANA_WELCOME_TEXT.format(models=models)


def model_panel_text(user: UserRD, model_key: str) -> str:
    from bot.utils.image_models import format_generations, get_image_model

    model = get_image_model(model_key)
    return (
        "Выберите модель для генерации.\n"
        f"Текущая модель: {model.title}\n"
        f"Стоимость: {format_generations(model.cost)}\n"
        f"Баланс: {format_generations(user.credits)}"
    )


def generation_started_text(task_id: str, model_key: str) -> str:
    from bot.utils.image_models import get_image_model

    model = get_image_model(model_key)
    return (
        "✅ Генерация запущена!\n"
        f"🆔 Задача: {task_id}\n"
        f"🍌 Модель: {model.title}\n"
        "Я пришлю результат, когда он будет готов."
    )


WITHDRAW_TEXT = "Вывод средств пока недоступен. Мы сообщим, когда он заработает."
TOPUP_METHODS_TEXT = "Выберите способ пополнения:"


@dataclass(frozen=True)
class TopupMethodInfo:
    key: str
    title_prefix: str
    currency_label: str
    button_prefix: str


@dataclass(frozen=True)
class TopupTariff:
    plan: str
    price: int
    credits: int
    songs: int


_TOPUP_METHODS = {
    "stars": TopupMethodInfo(
        key="stars",
        title_prefix="⭐️",
        currency_label="звёзд",
        button_prefix="⭐️",
    ),
    "card": TopupMethodInfo(
        key="card",
        title_prefix="💳",
        currency_label="руб.",
        button_prefix="💳",
    ),
}

_DEFAULT_TOPUP_TARIFFS: dict[str, list[TopupTariff]] = {
    "card": [
        TopupTariff(plan="10", price=10, credits=6, songs=3),
        TopupTariff(plan="20", price=20, credits=20, songs=10),
        TopupTariff(plan="30", price=30, credits=50, songs=25),
        TopupTariff(plan="40", price=40, credits=120, songs=60),
    ],
    "stars": [
        TopupTariff(plan="1", price=1, credits=6, songs=3),
        TopupTariff(plan="2", price=2, credits=20, songs=10),
        TopupTariff(plan="3", price=3, credits=50, songs=25),
        TopupTariff(plan="4", price=4, credits=120, songs=60),
    ],
}

logger = logging.getLogger(__name__)


def _parse_topup_tariffs(raw: str) -> list[TopupTariff]:
    tariffs: list[TopupTariff] = []
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":")]
        if len(parts) != 4:
            logger.warning("Неверный формат тарифа: %s", item)
            continue
        plan = parts[0]
        try:
            price = int(parts[1])
            credits = int(parts[2])
            songs = int(parts[3])
        except ValueError:
            logger.warning("Неверные числовые значения тарифа: %s", item)
            continue
        if price <= 0 or credits <= 0 or songs <= 0:
            logger.warning("Тариф должен быть положительным: %s", item)
            continue
        tariffs.append(
            TopupTariff(
                plan=plan,
                price=price,
                credits=credits,
                songs=songs,
            )
        )
    return tariffs


def _load_topup_tariffs() -> dict[str, list[TopupTariff]]:
    card_tariffs = _parse_topup_tariffs(se.topup.tariffs_card_raw)
    if not card_tariffs:
        card_tariffs = _DEFAULT_TOPUP_TARIFFS["card"]
    stars_tariffs = _parse_topup_tariffs(se.topup.tariffs_stars_raw)
    if not stars_tariffs:
        stars_tariffs = _DEFAULT_TOPUP_TARIFFS["stars"]
    return {
        "card": card_tariffs,
        "stars": stars_tariffs,
    }


_TOPUP_TARIFFS = _load_topup_tariffs()


def get_topup_method(method: str) -> TopupMethodInfo | None:
    return _TOPUP_METHODS.get(method)


def get_topup_tariffs(method: str) -> list[TopupTariff]:
    return list(_TOPUP_TARIFFS.get(method, []))


def get_topup_tariff(method: str, plan: str) -> TopupTariff | None:
    for tariff in _TOPUP_TARIFFS.get(method, []):
        if tariff.plan == plan:
            return tariff
    return None


def topup_tariffs_text(method: str) -> str:
    method_info = get_topup_method(method)
    if not method_info:
        return "Не удалось определить способ оплаты. Попробуйте снова."

    tariffs = get_topup_tariffs(method)
    if not tariffs:
        return "Тарифы временно недоступны. Попробуйте позже."

    if method_info.key == "stars":
        method_line = "⭐️ Купите генерации за звёзды."
    else:
        method_line = "💳 Купите генерации за рубли."
    return (
        f"💳 Пополнить баланс\n\n{method_line}\n\n"
        "🖌 Редактирование и генерация изображений"
    )


def main_menu_text(user: UserRD) -> str:
    return MAIN_MENU_TEXT.format(credits=user.credits)


def how_text(bot_name: str) -> str:
    return (
        f"🖼 Как работает бот {bot_name}\n\n"
        f"{bot_name} — самый простой способ редактировать и объединять фото.\n\n"
        "1️⃣ Выбираешь модель для генерации.\n"
        "2️⃣ Присылаешь 1-4 фотографии.\n"
        "3️⃣ Описываешь, что нужно изменить.\n"
        "4️⃣ Получаешь готовое изображение.\n\n"
        "💳 Если генерации закончатся, ты всегда можешь пополнить баланс в "
        "главном меню."
    )


def earn_text(
    *,
    bot_name: str,
    referrals_count: int,
    balance_kopeks: int,
    paid_kopeks: int,
    referral_payments_count: int,
    payout_kopeks: int,
    ref_link: str,
) -> str:
    return (
        f"💸 Зарабатывайте с {bot_name}!\n\n"
        "Получайте 20% от суммы оплат приглашенных пользователей "
        "в течение целого года!\n\n"
        "ℹ️ Как это работает?\n"
        "1️⃣ Вы публикуете реферальную ссылку на бота в соц сетях "
        "или отправляете друзьям\n"
        "2️⃣ Друзья пользуются ботом и оплачивают генерации\n"
        "3️⃣ 20% от всех оплат зачисляется на ваш баланс\n"
        "4️⃣ Сумму от 1000 руб можно вывести на карту\n\n"
        f"👥 Ваши рефералы: {referrals_count}\n"
        f"💰 Реферальный баланс: {format_rub(balance_kopeks)} руб.\n"
        f"💸 Выплачено: {format_rub(paid_kopeks)} руб.\n"
        f"📈 Платежи рефералов: {referral_payments_count}\n"
        f"⏳ Сумма на выдаче: {format_rub(payout_kopeks)} руб.\n"
        "🔗 Ваша реферальная ссылка:\n"
        f"{ref_link}\n\n"
        "📣 Приглашайте друзей и получайте 20% от всех их платежей "
        "в течение года!"
    )
