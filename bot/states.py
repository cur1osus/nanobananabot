from aiogram.fsm.state import State, StatesGroup


class BaseUserState(StatesGroup):
    main = State()


class ImageGenerationState(StatesGroup):
    waiting_photos = State()
    waiting_prompt = State()
    waiting_create_model = State()
    waiting_create_aspect = State()
    waiting_create_prompt = State()
    processing = State()


class WithdrawState(StatesGroup):
    amount = State()
    details = State()


class ManagerWithdrawState(StatesGroup):
    error_reason = State()


class VideoGenerationState(StatesGroup):
    settings = State()
    waiting_prompt = State()
    waiting_image = State()


class SpeechTestState(StatesGroup):
    waiting = State()
