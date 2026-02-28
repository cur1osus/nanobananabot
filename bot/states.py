from aiogram.fsm.state import State, StatesGroup


class BaseUserState(StatesGroup):
    main = State()


class MusicGenerationState(StatesGroup):
    prompt = State()
    style = State()
    title = State()
    waiting = State()
    topic_style = State()
    topic_text_menu = State()
    ai_result = State()


class WithdrawState(StatesGroup):
    amount = State()
    details = State()


class ManagerWithdrawState(StatesGroup):
    error_reason = State()


class SpeechTestState(StatesGroup):
    waiting = State()
