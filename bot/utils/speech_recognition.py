from __future__ import annotations

import base64
import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import aiohttp
from aiogram.types import Message
from openai import AsyncOpenAI

from bot.settings import se
from bot.utils.http import get_http_session

logger = logging.getLogger(__name__)


class SpeechRecognitionError(Exception):
    """Errors raised by the speech recognition agent."""


# Telegram voice — .oga (ogg/opus); whisper RouterAI принимает ogg напрямую,
# поэтому конвертация не нужна. Прочие форматы мапим по расширению.
_FORMAT_BY_SUFFIX = {
    ".oga": "ogg",
    ".ogg": "ogg",
    ".opus": "ogg",
    ".mp3": "mp3",
    ".mpeg": "mp3",
    ".mpga": "mp3",
    ".m4a": "m4a",
    ".wav": "wav",
    ".webm": "webm",
}


def _audio_format_from_path(file_path: str) -> str:
    return _FORMAT_BY_SUFFIX.get(Path(file_path).suffix.lower(), "ogg")


async def _transcribe_routerai(
    audio_bytes: bytes,
    audio_format: str,
    *,
    language: str | None = None,
) -> str:
    """STT через RouterAI whisper. RouterAI требует JSON-тело (НЕ multipart):
    {"model","input_audio":{"data":<b64>,"format"},"language"?} и возвращает
    {"text","usage"}. Доступен с сервера только через WireGuard-relay."""
    payload: dict[str, Any] = {
        "model": se.routerai.stt_model,
        "input_audio": {
            "data": base64.b64encode(audio_bytes).decode("ascii"),
            "format": audio_format,
        },
    }
    if language:
        payload["language"] = language

    url = f"{se.routerai.base_url.rstrip('/')}/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {se.routerai.api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=se.routerai.timeout)
    session = get_http_session()
    async with session.post(
        url, json=payload, headers=headers, timeout=timeout
    ) as resp:
        data = await resp.json(content_type=None)
        if resp.status >= 400:
            message = (data or {}).get("error", {})
            if isinstance(message, dict):
                message = message.get("message")
            raise SpeechRecognitionError(
                f"RouterAI STT error {resp.status}: {message or data}"
            )
    text = _extract_text(data)
    if not text:
        raise SpeechRecognitionError("Empty RouterAI transcription response.")
    return text


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
        # Один stat() ничтожен на фоне последующей сетевой загрузки файла —
        # выносить его в поток дороже самой проверки.
        if not path.is_file():  # noqa: ASYNC240
            raise SpeechRecognitionError(f"Audio file not found: {path}")

        params = {
            "model": self.model,
            "file": path,
            "response_format": response_format,
        }
        if language:
            params["language"] = language

        # response_format здесь динамический str, поэтому mypy не может выбрать
        # перегрузку SDK (они ключуются на Literal). Вызов корректен в рантайме.
        transcription = await self.client.audio.transcriptions.create(**params)  # type: ignore[call-overload]
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
    # Общий ClientSession переиспользует пул соединений/TLS вместо создания
    # новой сессии (и хендшейка) на каждое скачивание голосового.
    session = get_http_session()
    async with session.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return await response.read()


def _write_temp_audio_file(audio_bytes: bytes, suffix: str) -> str:
    # delete=False: файл переживает функцию и удаляется позже в _cleanup_temp_file.
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(audio_bytes)
        return temp_file.name


def _cleanup_temp_file(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


async def transcribe_message_audio(
    message: Message,
    *,
    language: str | None = None,
) -> str:
    file_id = _extract_audio_file_id(message)
    if not file_id:
        raise SpeechRecognitionError("Message does not contain audio or voice.")

    bot = message.bot
    if bot is None:
        raise SpeechRecognitionError("Bot instance is not bound to the message.")

    file = await bot.get_file(file_id)
    file_path = file.file_path or ""
    if not file_path:
        raise SpeechRecognitionError("Telegram file path is empty.")

    bot_token = getattr(bot, "token", "")
    if not bot_token:
        raise SpeechRecognitionError("Bot token is not available for download.")

    audio_bytes = await _download_telegram_file(bot_token, file_path)

    # Основной путь — RouterAI whisper (если задан ключ); при любой ошибке
    # откатываемся на VseGpt, чтобы голосовой ввод не падал.
    if se.routerai.api_key:
        try:
            audio_format = _audio_format_from_path(file_path)
            return await _transcribe_routerai(
                audio_bytes, audio_format, language=language
            )
        except Exception:
            logger.warning("RouterAI STT не удался, фолбэк на VseGpt", exc_info=True)

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
