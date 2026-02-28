from aiogram.utils.keyboard import ReplyKeyboardBuilder

CANCEL_BUTTON_TEXT = "Отмена"


async def rk_cancel():
    builder = ReplyKeyboardBuilder()
    builder.button(text=CANCEL_BUTTON_TEXT)
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)
