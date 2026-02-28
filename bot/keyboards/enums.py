from enum import Enum


class MusicBackTarget(str, Enum):
    HOME = "home"
    TEXT_MENU = "text_menu"
    MODE = "mode"
    STYLE = "style"
    TITLE = "title"
    PROMPT = "prompt"
    TOPIC_STYLE = "topic_style"
    TOPIC_TEXT_MENU = "topic_text_menu"
    AI_RESULT = "ai_result"
