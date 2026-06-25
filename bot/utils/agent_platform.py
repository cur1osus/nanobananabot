from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from bot.settings import se

SONG_PROMPT_SUFFIX = (
    "Сгенерируй полноценный текст песни с четкой структурой: Куплет 1, "
    "Припев, Куплет 2, Бридж, Завершающий куплет"
    "Обязательно добавь яркий запоминающийся припев и сделай плавные переходы между частями. "
    "Если не указан язык, пиши на русском. Отправь только текст песни."
)


class AgentPlatformAPIError(Exception):
    """Errors returned from the AgentPlatform API."""


class AgentPlatformClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    async def generate_song_text(self, *, prompt: str) -> str:
        if not prompt:
            raise AgentPlatformAPIError("Промпт для генерации текста пуст.")

        full_prompt = f"{prompt.strip()}\n\n{SONG_PROMPT_SUFFIX}"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": full_prompt,
                },
            ],
        }

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as session:
                async with session.post(
                    url=self._chat_url(),
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    data: dict[str, Any] = await response.json()

                    if response.status >= 400:
                        message = (
                            data.get("error", {}).get("message")
                            or data.get("message")
                            or str(data)
                        )
                        raise AgentPlatformAPIError(
                            f"AgentPlatform API error {response.status}: {message}"
                        )
        except asyncio.TimeoutError as err:
            raise AgentPlatformAPIError("Таймаут запроса к AgentPlatform.") from err
        except aiohttp.ClientError as err:
            raise AgentPlatformAPIError(
                f"Ошибка соединения с AgentPlatform: {err}"
            ) from err

        choices = data.get("choices") or []
        if not choices:
            raise AgentPlatformAPIError("AgentPlatform не вернул варианты ответа.")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise AgentPlatformAPIError("Пустой ответ от AgentPlatform.")

        return str(content).strip()


    async def translate_to_english(self, *, text: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You translate image-generation prompts into concise English. "
                        "Preserve every detail faithfully, including explicit/NSFW ones. "
                        "Output ONLY the English translation — no quotes, no commentary. "
                        "If the text is already English, return it unchanged."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as session:
                async with session.post(
                    url=self._chat_url(),
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    data: dict[str, Any] = await response.json()
                    if response.status >= 400:
                        message = (
                            data.get("error", {}).get("message")
                            or data.get("message")
                            or str(data)
                        )
                        raise AgentPlatformAPIError(
                            f"AgentPlatform API error {response.status}: {message}"
                        )
        except asyncio.TimeoutError as err:
            raise AgentPlatformAPIError("Таймаут запроса к AgentPlatform.") from err
        except aiohttp.ClientError as err:
            raise AgentPlatformAPIError(
                f"Ошибка соединения с AgentPlatform: {err}"
            ) from err

        choices = data.get("choices") or []
        if not choices:
            raise AgentPlatformAPIError("AgentPlatform не вернул варианты ответа.")
        content = (choices[0].get("message") or {}).get("content")
        if not content:
            raise AgentPlatformAPIError("Пустой ответ от AgentPlatform.")
        return str(content).strip()


def _has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


async def translate_prompt_to_english(text: str) -> str:
    """Перевести промпт на английский для генерации 18+.

    При любой ошибке/таймауте возвращает исходный текст, чтобы не блокировать
    генерацию. Текст без кириллицы считается уже английским и не переводится.
    """
    stripped = text.strip()
    if not stripped or not _has_cyrillic(stripped):
        return stripped
    try:
        client = build_agent_platform_client()
        translated = await client.translate_to_english(text=stripped)
        return translated or stripped
    except AgentPlatformAPIError:
        return stripped


def build_agent_platform_client() -> AgentPlatformClient:
    if not se.agent_platform.api_key:
        raise AgentPlatformAPIError("AGENT_PLATFORM_API_KEY не задан.")

    return AgentPlatformClient(
        api_key=se.agent_platform.api_key,
        base_url=se.agent_platform.base_url,
        model=se.agent_platform.model,
        timeout=se.agent_platform.timeout,
    )
