from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from bot.db.redis.user_model import UserRD
from bot.settings import se
from bot.utils.formatting import format_rub

MAIN_MENU_TEXT = (
    "🏠 Главное меню\n💰 Ваш баланс: {credits} Hit$\n🎵 Что вы хотите сделать?"
)
MY_TRACKS_MENU_TEXT = (
    "🎧 Ниже все треки, которые были тобой созданы.\n"
    "Нажми на название трека, чтобы получить подробную информацию о нём."
)
MY_TRACKS_EMPTY_TEXT = "Пока нет ни одного трека. Создай новую песню в главном меню."

BOT_INFO_TEXT = (
    "Пиши песни, создавай тексты, генерируй собственные видео.\n\n"
    "Сотрудничество/вопросы: @HitSongMaker_support"
)

CONTACTS_TEXT = (
    "📞 Контакты\n\n"
    "Официальный канал: @HitSongMaker_oficial\n"
    "Официальный сайт: HitSongMaker.com\n"
    "Чат: @HitSongMaker_chat"
)


BOT_DESCRIPTION_TEXT = (
    "🎵 Добро пожаловать в HitSongMaker!\n\n"
    "Здесь ты можешь:\n"
    "• создавать песни с нуля\n"
    "• писать тексты с помощью AI\n"
    "• генерировать инструменталы\n\n"
    "Все права на созданные треки принадлежат тебе 💿\n\n"
    "Жми «🎼 Создать новую песню» и начнём 🚀"
)

LYRICS_MENU_TEXT = (
    "Начнем с создания текста для песни 🎶\n\n"
    "Ты можешь:\n"
    "1️⃣ Выбрать готовый повод\n"
    "2️⃣ Сгенерировать текст песни по описанию с помощью AI\n"
    "3️⃣ 📝 Отправить готовый текст вручную"
)


def music_topic_style_text(topic_key: str) -> str:
    from bot.utils.music_topics import get_music_topic_type_line

    topic_line = get_music_topic_type_line(topic_key) or ""
    return (
        f"{topic_line}\n"
        "В каком жанре делаем песню?\n"
        "Можешь выбрать из списка или написать свой ✍️"
    )


def music_topic_custom_style_text(topic_key: str) -> str:
    from bot.utils.music_topics import get_music_topic_type_line

    topic_line = get_music_topic_type_line(topic_key) or ""
    return (
        f"{topic_line}\n"
        "Опиши, каким должен быть трек 🎧\n"
        "• на кого похож стиль\n"
        "• быстрый или медленный темп\n"
        "• какие инструменты\n\n"
        "Можешь написать текстом или отправить голосом — я пойму 😉"
    )


def music_topic_text_menu_text(topic_key: str, style: str) -> str:
    from bot.utils.music_topics import get_music_topic_style_line

    style_line = get_music_topic_style_line(topic_key) or ""
    genre_line = f"Жанр: 🎶 {style} (или любой, который тебе нравится)"
    return (
        f"{style_line}\n"
        f"{genre_line}\n\n"
        "А теперь самое важное!\n"
        "Есть повод и стиль — пора сделать песню по-настоящему твоей 🎯\n\n"
        "Выбирай: создать текст с помощью ИИ или использовать уже готовый вариант."
    )


def music_instrumental_style_text() -> str:
    return (
        "Тип песни: 🎹 Инструментал\n"
        "Теперь выбери жанр или введи свой вариант сообщением."
    )


def music_ai_prompt_text() -> str:
    return (
        "💬 Поделись идеями для песни:\n"
        "— Про кого или о чём этот трек\n"
        "— Какие эмоции он должен вызывать\n"
        "— Есть ли фразы, события или образы, которые важно упомянуть\n"
        "— Какое настроение хочется передать\n\n"
        "✍️ Можешь написать текстом или рассказать голосом — я разберусь."
    )


def music_manual_prompt_text() -> str:
    return (
        "✍️ Отправьте текст вашей песни в чат.\n"
        "⚠️ Важно:\n"
        "Не присылайте тексты известных песен — они не пройдут проверку сервиса "
        "на авторские права.\n\n"
        "Пример текста песни:\n"
        "Куплет 1\n"
        "Строчки куплета\n"
        "Строчки куплета\n\n"
        "Припев\n"
        "Строчки припева\n\n"
        "Куплет 2\n"
        "Строчки второго куплета\n\n"
        "Вы можете использовать любые названия секций:\n"
        "бридж, аутро и т.д."
    )


def music_ai_result_text(style: str, lyrics: str) -> str:
    style_label = style or "диско 90-х"
    style_label = style_label.lower()
    return (
        "Отлично, тогда доверься мне! Я набросал первый вариант текста "
        f"в стиле {style_label}, чтобы было от чего отталкиваться. "
        "Посмотри, как тебе? Может, что-то хочется изменить, добавить или убрать?\n\n"
        f"Текст песни:\n{lyrics}"
    )


MUSIC_AI_EDIT_TEXT = (
    "Напиши, что именно нужно изменить ✍️\nЯ учту пожелания и пришлю обновленный текст"
)


MUSIC_STYLE_TEXT = "Выбери стиль или введи свой сообщением:"
MUSIC_TITLE_TEXT = (
    "🎵 Добавь название трека.\n"
    "После этого начнётся генерация песни.\n\n"
    "🔄 Ты получишь сразу 2 версии трека\n"
    "💳 Стоимость: 2 Hit$"
)
MUSIC_PROMPT_TEXT = "Опиши промпт для генерации:"
MUSIC_PROMPT_INSTRUMENTAL_TEXT = (
    "📝 Опиши промпт для инструментала.\n"
    "Расскажи, каким он должен быть: настроение, стиль, темп, инструменты.\n\n"
    "Можно текстом или голосом."
)
MUSIC_PROMPT_AI_TEXT = "Опиши, какой текст песни нужно сгенерировать:"
MUSIC_PROMPT_MANUAL_TEXT = "Введи текст песни вручную:"
MUSIC_STYLE_CUSTOM_TEXT = "Введи стиль сообщением (например, Jazz, Pop, Rock)."
MUSIC_INSTRUMENTAL_STYLE_CUSTOM_TEXT = "Введи жанр сообщением (например, Pop, Rock)."
MUSIC_NO_CREDITS_TEXT = (
    "😕 Недостаточно Hit$ для генерации музыки.\n"
    "Для этого нужно 2 Hit$.\n\n"
    "Пожалуйста, пополните баланс и попробуйте снова."
)


def music_generation_started_text(task_id: str, title: str) -> str:
    return (
        "✅ Отлично, приступаю!\n"
        f"🆔 Задача: {task_id}\n"
        f"🎵 Название трека: {title}\n"
        "⏳ Примерное время генерации: 5 минут\n"
        "Я пришлю файл в чат, когда трек будет готов.\n\n"
        "Все созданные песни доступны в разделе «🎧 Мои треки»"
    )


def music_instrumental_title_text(style: str) -> str:
    style_label = style.strip()
    if style_label:
        genre_line = f"Жанр песни: 🎶 {style_label} (или то, что ввел пользователь)"
    else:
        genre_line = "Жанр песни: 🎶 то, что ввел пользователь"
    return f"Тип песни: 🎹 Инструментал\n{genre_line}\n\n{MUSIC_TITLE_TEXT}"


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
        method_line = "⭐️ Купите Hit$ для создания песен за звёзды."
    else:
        method_line = "💳 Купите Hit$ для создания песен."
    return (
        "💳 Пополнить баланс\n\n"
        f"{method_line}\n\n"
        "🎵 Генерация песни — 2 Hit$\n"
        "Одна генерация даёт сразу 2 варианта трека"
    )


def main_menu_text(user: UserRD) -> str:
    return MAIN_MENU_TEXT.format(credits=user.credits)


def how_text(bot_name: str) -> str:
    return (
        f"🎵 Как работает бот {bot_name}\n\n"
        f"{bot_name} — самый простой способ создать свою песню, даже если ты "
        "никогда этим не занимался.\n\n"
        "1️⃣ Ты создаёшь текст песни — сам или с помощью AI.\n"
        "2️⃣ Бот генерирует песню на этот текст "
        "(1 генерация = 2 версии трека).\n"
        "3️⃣ Генерация текста стоит 1 Hit$.\n"
        "4️⃣ Генерация песни стоит 2 Hit$.\n\n"
        "💳 Если Hit$ закончатся, ты всегда можешь пополнить баланс в "
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
        "2️⃣ Друзья пользуются ботом и оплачивают песни\n"
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


def my_tracks_details_text(
    *,
    title: str,
    created_at: datetime | None,
    status_label: str | None = None,
    song_type: str | None = None,
    genre: str | None = None,
) -> str:
    lines = [f"🎵 Название: {title}"]
    if created_at:
        lines.append(f"📅 Дата создания: {created_at:%d.%m.%Y %H:%M}")
    if status_label:
        lines.append(f"⚙️ Статус: {status_label}")
    if song_type:
        lines.append(f"🎯 Тип песни: {song_type}")
    if genre:
        lines.append(f"🎶 Жанр песни: {genre}")
    return "\n".join(lines)


def my_tracks_lyrics_text(*, title: str, lyrics: str) -> str:
    return f"Текст песни «{title}»:\n\n{lyrics}"
