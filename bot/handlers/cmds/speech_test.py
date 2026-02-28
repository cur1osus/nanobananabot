from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.states import SpeechTestState
from bot.utils.speech_recognition import (
    SpeechRecognitionError,
    transcribe_message_audio,
)

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("stt_test"))
async def stt_test_start(
    message: Message,
    user: UserRD,
    state: FSMContext,
) -> None:
    if user.role != UserRole.ADMIN.value:
        await message.answer("У вас нет прав на выполнение этой команды.")
        return

    await state.set_state(SpeechTestState.waiting)
    await message.answer("Пришлите голосовое или аудиофайл для распознавания.")


@router.message(SpeechTestState.waiting)
async def stt_test_receive(
    message: Message,
    user: UserRD,
    state: FSMContext,
) -> None:
    if user.role != UserRole.ADMIN.value:
        await state.clear()
        await message.answer("У вас нет прав на выполнение этой команды.")
        return

    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("Тест распознавания отменен.")
        return

    if not (message.voice or message.audio):
        await message.answer("Пришлите голосовое или аудиофайл.")
        return

    try:
        text = await transcribe_message_audio(message, language="ru")
    except SpeechRecognitionError as err:
        logger.warning("Не удалось распознать аудио для теста: %s", err)
        await message.answer("Не удалось распознать аудио.")
        return

    await state.clear()
    await message.answer(f"Результат распознавания:\n{text}")
