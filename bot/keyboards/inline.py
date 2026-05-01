from typing import Final

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.factories import (
    CreateAspectRatio,
    ImageNav,
    ImageResultAction,
    InfoPeriod,
    MenuAction,
    ModelMenu,
    ModelSelect,
    TopupMethod,
    TopupPlan,
    VideoAspectRatio,
    VideoNav,
    VideoSetting,
    WithdrawAction,
)
from bot.utils.image_models import IMAGE_MODELS, DEFAULT_IMAGE_MODEL_KEY
from bot.utils.texts import get_topup_method, get_topup_tariffs
from bot.utils.video_models import KLING_MODELS, VIDEO_RATIO_MAP, VIDEO_RATIOS, get_kling_model

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
    builder.button(
        text="🏠 В главное меню",
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_image_waiting_photos() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔙 К выбору модели",
        callback_data=ModelMenu().pack(),
    )
    builder.button(
        text="🏠 В главное меню",
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_image_result_actions() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Сгенерировать похожее",
        callback_data=ImageResultAction(action="similar").pack(),
    )
    builder.button(
        text="1️⃣ Начать с 1-го фото",
        callback_data=ImageResultAction(action="first_photo").pack(),
    )
    builder.button(
        text="🖼 Начать заново",
        callback_data=ImageResultAction(action="restart").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_prompt_nav() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="↩️ Назад",
        callback_data=ImageNav(action="to_photos").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_create_prompt_nav() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔙 К выбору формата",
        callback_data=ImageNav(action="to_create_aspect").pack(),
    )
    builder.button(
        text="🏠 В главное меню",
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_create_aspect_ratio() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    options = (
        ("auto", "🔁 Auto"),
        ("1x1", "1:1"),
        ("4x3", "4:3"),
        ("3x4", "3:4"),
        ("3x2", "3:2"),
        ("2x3", "2:3"),
        ("16x9", "16:9"),
        ("9x16", "9:16"),
        ("21x9", "21:9"),
        ("5x4", "5:4"),
        ("4x5", "4:5"),
    )
    for ratio, label in options:
        builder.button(
            text=label,
            callback_data=CreateAspectRatio(ratio=ratio).pack(),
        )
    builder.button(
        text="🔙 К выбору модели",
        callback_data=ModelMenu().pack(),
    )
    builder.button(
        text="🏠 В главное меню",
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(2, 3, 3, 3, 1, 1)
    return builder.as_markup()


async def ik_main(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🖌 Редактирование фото",
        callback_data=MenuAction(action="edit").pack(),
    )
    builder.button(
        text="✨ Генерация изображения",
        callback_data=MenuAction(action="image").pack(),
    )
    builder.button(
        text="🎬 Создать видео",
        callback_data=MenuAction(action="video").pack(),
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
        text="✨ Генерация изображения",
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
        text="💳 Карта / СБП",
        callback_data=TopupMethod(method="card").pack(),
    )
    builder.button(
        text="⭐️ Звёзды",
        callback_data=TopupMethod(method="stars").pack(),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


async def ik_topup_plans(method: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    method_info = get_topup_method(method)
    tariffs = get_topup_tariffs(method)
    for tariff in tariffs:
        if method_info and method_info.key == "stars":
            text = f"{tariff.price} ⭐️ → {tariff.credits} генераций"
        else:
            text = f"{tariff.price} ₽ → {tariff.credits} генераций"
        builder.button(
            text=text,
            callback_data=TopupPlan(method=method, plan=tariff.plan).pack(),
        )
    builder.button(
        text="↩️ Назад",
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
    periods = [("day", "День"), ("week", "Неделя"), ("month", "Месяц"), ("all", "Всё время")]
    for key, label in periods:
        prefix = "✅ " if key == selected else ""
        builder.button(
            text=f"{prefix}{label}",
            callback_data=InfoPeriod(period=key).pack(),
        )
    builder.button(
        text="💳 Аккаунт",
        callback_data=MenuAction(action="runware_account").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(3, 1, 1, 1)
    return builder.as_markup()


async def ik_runware_account_back() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="← К статистике",
        callback_data=InfoPeriod(period="day").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_video_settings(
    model_key: str,
    duration: int,
    aspect_ratio: str,
    with_audio: bool,
) -> InlineKeyboardMarkup:
    model = get_kling_model(model_key)
    builder = InlineKeyboardBuilder()
    row_sizes: list[int] = []

    # Промпт + Изображение
    builder.button(text="📝 Промпт", callback_data=VideoNav(action="set_prompt").pack())
    builder.button(text="🖼 Изображение", callback_data=VideoNav(action="set_image").pack())
    row_sizes.append(2)

    # Звук — только если модель поддерживает
    if model.supports_sound:
        audio_label = "✅ Со звуком" if with_audio else "Без звука"
        builder.button(
            text=audio_label,
            callback_data=VideoSetting(setting="audio", value="0" if with_audio else "1").pack(),
        )
        row_sizes.append(1)

    # Длительность — только если модель поддерживает
    if model.supports_duration:
        for d in (5, 10):
            label = f"✅ {d} сек." if duration == d else f"{d} сек."
            builder.button(
                text=label,
                callback_data=VideoSetting(setting="duration", value=str(d)).pack(),
            )
        row_sizes.append(2)

    # Модели (всегда по 2 в ряд)
    for m in KLING_MODELS:
        label = f"✅ {m.title}" if m.key == model_key else m.title
        builder.button(
            text=label,
            callback_data=VideoSetting(setting="model", value=m.key).pack(),
        )
    row_sizes.extend([2, 2])

    # Соотношение сторон — только если модель поддерживает
    if model.supports_dimensions:
        for key, ratio in VIDEO_RATIO_MAP.items():
            label = f"✅ {ratio}" if ratio == aspect_ratio else ratio
            builder.button(
                text=label,
                callback_data=VideoAspectRatio(ratio=key).pack(),
            )
        row_sizes.append(3)

    # Назад + Генерация
    builder.button(text="← Назад", callback_data=MenuAction(action="home").pack())
    builder.button(text="🎬 Начать генерацию", callback_data=VideoNav(action="generate").pack())
    row_sizes.append(2)

    builder.adjust(*row_sizes)
    return builder.as_markup()


async def ik_video_back_to_settings() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="← К настройкам",
        callback_data=VideoNav(action="back_to_settings").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_back_home() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()
