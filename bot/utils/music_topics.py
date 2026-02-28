from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class MusicTopicOption:
    key: str
    label: str
    emoji: str
    type_suffix: str
    style_emoji: str
    style_desc: str


MUSIC_TOPIC_OPTIONS: Final[list[MusicTopicOption]] = [
    MusicTopicOption(
        key="birthday",
        label="День рождения",
        emoji="🎂",
        type_suffix="в весёлом стиле",
        style_emoji="🎉",
        style_desc="с улыбкой и весельем",
    ),
    MusicTopicOption(
        key="confession",
        label="Признание",
        emoji="❤️",
        type_suffix="в романтичном стиле",
        style_emoji="💞",
        style_desc="с нежностью и теплом",
    ),
    MusicTopicOption(
        key="holiday",
        label="Праздник",
        emoji="🎉",
        type_suffix="в праздничном стиле",
        style_emoji="🎊",
        style_desc="с атмосферой праздника",
    ),
    MusicTopicOption(
        key="wedding",
        label="Свадьба",
        emoji="💍",
        type_suffix="в трогательном стиле",
        style_emoji="💍",
        style_desc="о любви и счастье",
    ),
    MusicTopicOption(
        key="support",
        label="Поддержка",
        emoji="💪",
        type_suffix="в вдохновляющем стиле",
        style_emoji="💪",
        style_desc="с поддержкой и силой",
    ),
    MusicTopicOption(
        key="prank",
        label="Розыгрыш",
        emoji="😂",
        type_suffix="в шуточном стиле",
        style_emoji="😂",
        style_desc="с юмором и сюрпризом",
    ),
]


def get_music_topic_label(topic_key: str) -> str | None:
    for option in MUSIC_TOPIC_OPTIONS:
        if option.key == topic_key:
            return option.label
    return None


def get_music_topic_option(topic_key: str) -> MusicTopicOption | None:
    for option in MUSIC_TOPIC_OPTIONS:
        if option.key == topic_key:
            return option
    return None


def get_music_topic_type_line(topic_key: str) -> str | None:
    option = get_music_topic_option(topic_key)
    if not option:
        return None
    return f"🎵 Тип песни: {option.emoji} {option.label}, {option.type_suffix}"


def get_music_topic_style_line(topic_key: str) -> str | None:
    option = get_music_topic_option(topic_key)
    if not option:
        return None
    return f"Стиль песни: {option.style_emoji} {option.label}, {option.style_desc}"
