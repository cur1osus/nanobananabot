from typing import Final

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.enums import MusicBackTarget
from bot.keyboards.factories import (
    MenuAction,
    MusicBack,
    MusicStyle,
    MusicTextAction,
    MusicTopic,
    MyTrackAction,
    MyTracksPage,
)
from bot.utils.music_topics import MUSIC_TOPIC_OPTIONS

LIMIT_BUTTONS: Final[int] = 100
BACK_BUTTON_TEXT = "🔙 Назад"
TOPIC_STYLE_OPTIONS: Final[list[tuple[str, str]]] = [
    ("🎵 Поп", "Поп"),
    ("🎤 Рэп / Хип-хоп", "Рэп / Хип-хоп"),
    ("🕺 Диско 90-х", "Диско 90-х"),
    ("🎸 Рок", "Рок"),
    ("🎙️ Шансон", "Шансон"),
    ("🎻 Классика", "Классика"),
    ("Инди", "Инди"),
    ("🎸 Акустика", "Акустика"),
]


async def ik_my_tracks_list(
    items: list[tuple[int, str]],
    *,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for track_id, label in items[: LIMIT_BUTTONS - 1]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=MyTrackAction(
                        action="detail", track_id=track_id
                    ).pack(),
                )
            ]
        )

    if total_pages > 1:
        nav_buttons: list[InlineKeyboardButton] = []
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=MyTracksPage(page=page - 1).pack(),
                )
            )
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=MyTracksPage(page=page + 1).pack(),
                )
            )
        if nav_buttons:
            rows.append(nav_buttons)

    rows.append(
        [
            InlineKeyboardButton(
                text=BACK_BUTTON_TEXT,
                callback_data=MenuAction(action="home").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def ik_my_track_detail(
    track_id: int,
    *,
    show_lyrics: bool = True,
    show_audio: bool = True,
    show_retry: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if show_audio:
        builder.button(
            text="🎵 Отправить аудио",
            callback_data=MyTrackAction(action="send_audio", track_id=track_id).pack(),
        )
    if show_lyrics:
        builder.button(
            text="📝 Показать текст песни",
            callback_data=MyTrackAction(action="lyrics", track_id=track_id).pack(),
        )
    if show_retry:
        builder.button(
            text="🔄 Повторить генерацию",
            callback_data=MyTrackAction(action="retry", track_id=track_id).pack(),
        )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="tracks").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_music_text_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in MUSIC_TOPIC_OPTIONS:
        builder.button(
            text=f"{option.emoji} {option.label}",
            callback_data=MusicTopic(topic=option.key).pack(),
        )
    builder.button(
        text="🤖 Создать текст через ИИ (1 кредит)",
        callback_data=MusicTextAction(action="ai").pack(),
    )
    builder.button(
        text="📝 Отправить готовый текст",
        callback_data=MusicTextAction(action="manual").pack(),
    )
    builder.button(
        text="🎹 Инструментал без слов (2 кредита)",
        callback_data=MusicTextAction(action="instrumental").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


async def ik_music_topic_styles() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, value in TOPIC_STYLE_OPTIONS:
        builder.button(
            text=label,
            callback_data=MusicStyle(style=value).pack(),
        )
    builder.button(
        text="✨ Свой вариант",
        callback_data=MusicStyle(style="custom").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MusicBack(target=MusicBackTarget.TEXT_MENU.value).pack(),
    )
    builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()


async def ik_music_topic_text_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🤖 Создать текст через ИИ (1 кредит)",
        callback_data=MusicTextAction(action="ai").pack(),
    )
    builder.button(
        text="📝 Отправить готовый текст",
        callback_data=MusicTextAction(action="manual").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MusicBack(target=MusicBackTarget.TOPIC_STYLE.value).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_music_ai_result() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛠️ Исправить текст с ИИ (1 кредит)",
        callback_data=MusicTextAction(action="ai_edit").pack(),
    )
    builder.button(
        text="🚀 Сгенерировать песню (2 кредита)",
        callback_data=MusicTextAction(action="generate_song").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MusicBack(target=MusicBackTarget.PROMPT.value).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_music_manual_prompt(
    *,
    back_to: MusicBackTarget,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🤖 Создать текст через ИИ (1 кредит)",
        callback_data=MusicTextAction(action="ai").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MusicBack(target=back_to.value).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_no_credits(
    *,
    back_to: MusicBackTarget,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Пополнить",
        callback_data=MenuAction(action="topup").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MusicBack(target=back_to.value).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def ik_music_styles() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🎤 Pop",
        callback_data=MusicStyle(style="Pop").pack(),
    )
    builder.button(
        text="🎸 Rock",
        callback_data=MusicStyle(style="Rock").pack(),
    )
    builder.button(
        text="🎷 Jazz",
        callback_data=MusicStyle(style="Jazz").pack(),
    )
    builder.button(
        text="🎻 Classical",
        callback_data=MusicStyle(style="Classical").pack(),
    )
    builder.button(
        text="🎧 Electronic",
        callback_data=MusicStyle(style="Electronic").pack(),
    )
    builder.button(
        text="🎹 Lo-fi",
        callback_data=MusicStyle(style="Lo-fi").pack(),
    )
    builder.button(
        text="🎼 Ambient",
        callback_data=MusicStyle(style="Ambient").pack(),
    )
    builder.button(
        text="🎙 Hip-Hop",
        callback_data=MusicStyle(style="Hip-Hop").pack(),
    )
    builder.button(
        text="✏️ Свой стиль",
        callback_data=MusicStyle(style="custom").pack(),
    )
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MusicBack(target=MusicBackTarget.TITLE.value).pack(),
    )
    builder.button(
        text="🏠 В главное меню",
        callback_data=MenuAction(action="home").pack(),
    )
    builder.adjust(2, 2, 2, 2, 1, 2)
    return builder.as_markup()


async def ik_music_back_home(
    back_to: MusicBackTarget,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BACK_BUTTON_TEXT,
        callback_data=MusicBack(target=back_to.value).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()
