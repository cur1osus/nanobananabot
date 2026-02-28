from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import aiohttp
from aiogram.types import Message
from openai import AsyncOpenAI

from bot.settings import se


class SpeechRecognitionError(Exception):
    """Errors raised by the speech recognition agent."""


class SpeechRecognitionAgent:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 60,
    ) -> None:
        if not api_key:
            raise SpeechRecognitionError("VSEGPT_API_KEY is not set.")
        self.model = model
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    async def transcribe_file(
        self,
        file_path: str | Path,
        *,
        language: str | None = None,
        response_format: str = "json",
    ) -> str:
        path = Path(file_path)
        if not path.is_file():
            raise SpeechRecognitionError(f"Audio file not found: {path}")

        params = {
            "model": self.model,
            "file": path,
            "response_format": response_format,
        }
        if language:
            params["language"] = language

        transcription = await self.client.audio.transcriptions.create(**params)
        text = _extract_text(transcription)
        if not text:
            raise SpeechRecognitionError("Empty transcription response.")
        return text


def _extract_text(transcription: Any) -> str:
    if isinstance(transcription, str):
        return transcription.strip()
    text = getattr(transcription, "text", None)
    if text:
        return str(text).strip()
    if isinstance(transcription, dict):
        text = transcription.get("text")
        if text:
            return str(text).strip()
    return ""


def build_speech_recognition_agent() -> SpeechRecognitionAgent:
    return SpeechRecognitionAgent(
        api_key=se.vsegpt.api_key,
        base_url=se.vsegpt.base_url,
        model=se.vsegpt.stt_model,
        timeout=se.vsegpt.timeout,
    )


def _extract_audio_file_id(message: Message) -> str | None:
    if message.voice:
        return message.voice.file_id
    if message.audio:
        return message.audio.file_id
    return None


async def _download_telegram_file(bot_token: str, file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()


def _write_temp_audio_file(audio_bytes: bytes, suffix: str) -> str:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.write(audio_bytes)
    temp_file.flush()
    temp_file.close()
    return temp_file.name


def _cleanup_temp_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


async def transcribe_message_audio(
    message: Message,
    *,
    language: str | None = None,
) -> str:
    file_id = _extract_audio_file_id(message)
    if not file_id:
        raise SpeechRecognitionError("Message does not contain audio or voice.")

    file = await message.bot.get_file(file_id)
    file_path = file.file_path or ""
    if not file_path:
        raise SpeechRecognitionError("Telegram file path is empty.")

    bot_token = getattr(message.bot, "token", "")
    if not bot_token:
        raise SpeechRecognitionError("Bot token is not available for download.")

    audio_bytes = await _download_telegram_file(bot_token, file_path)
    suffix = Path(file_path).suffix or ".ogg"
    temp_path = _write_temp_audio_file(audio_bytes, suffix)
    try:
        agent = build_speech_recognition_agent()
        return await agent.transcribe_file(temp_path, language=language)
    finally:
        _cleanup_temp_file(temp_path)


async def get_vsegpt_balance() -> float:
    """Get VseGpt API balance (credits)."""
    if not se.vsegpt.api_key:
        raise SpeechRecognitionError("VSEGPT_API_KEY is not set.")

    url = "https://api.vsegpt.ru/v1/balance"
    headers = {
        "Authorization": f"Bearer {se.vsegpt.api_key}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                raise SpeechRecognitionError(
                    f"VseGpt API error {response.status}: {text}"
                )

            data = await response.json()
            if data.get("status") != "ok":
                reason = data.get("reason", "Unknown error")
                raise SpeechRecognitionError(f"VseGpt API error: {reason}")

            credits_data = data.get("data", {})
            credits = credits_data.get("credits", 0)
            return float(credits)
