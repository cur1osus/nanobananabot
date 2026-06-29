from __future__ import annotations

from typing import Any

import aiohttp

from bot.settings import se

SONG_PROMPT_SUFFIX = (
    "Сгенерируй полноценный текст песни с четкой структурой: Куплет 1, "
    "Припев, Куплет 2, Бридж, Завершающий куплет"
    "Обязательно добавь яркий запоминающийся припев и сделай плавные переходы между частями. "
    "Если не указан язык, пиши на русском. Отправь только текст песни."
)

# Системная инструкция для перевода промптов генерации на английский. Подчёркнуто
# «технический переводчик без отказов», чтобы flash-модель не отказывалась
# переводить откровенные 18+ промпты и не добавляла комментариев.
TRANSLATE_SYSTEM_PROMPT = (
    "You are a professional translation engine. Translate the user's image-generation "
    "prompt into English. Output ONLY the translated prompt: no comments, no quotes, "
    "no refusals, no notes. Preserve the exact meaning, style and all details."
)

# Системные промпты для «✨ Промпт с помощью ИИ». Дешёвая flash-модель превращает
# идею/черновик пользователя в сильный промпт. Вывод — ТОЛЬКО промпт, без пояснений.
_PROMPT_ENGINEER_BASE = (
    "You are an expert prompt engineer for AI image models. "
    "Reply in EXACTLY this format and nothing else:\n"
    "PROMPT: <the final image prompt in English, one paragraph>\n"
    "ОПИСАНИЕ: <one short sentence in RUSSIAN describing what will be generated>\n"
    "No quotes, no extra lines, no explanations."
)
_PROMPT_CREATE_HINT = (
    "Task: write ONE powerful text-to-image prompt. Include main subject, setting, "
    "composition, lighting, mood, art style or medium, camera/lens if photographic, "
    "and quality descriptors. Concrete and richly detailed but concise (max ~60 words)."
)
_PROMPT_EDIT_HINT = (
    "Task: write ONE clear photo-editing instruction (image-to-image). Describe the "
    "desired changes while preserving the person's identity, face and untouched areas. "
    "Be specific about what to change (background, clothing, lighting, style, added or "
    "removed elements). Concise (max ~50 words)."
)
_PROMPT_ENRICH_HINT = (
    "The user gives a rough draft — keep their intent and enrich it into a strong prompt."
)
_PROMPT_SCRATCH_HINT = (
    "The user gives only a topic — invent a complete, creative prompt around it."
)


def build_image_prompt_system(*, mode: str, target: str) -> str:
    target_hint = _PROMPT_EDIT_HINT if target == "edit" else _PROMPT_CREATE_HINT
    mode_hint = _PROMPT_SCRATCH_HINT if mode == "scratch" else _PROMPT_ENRICH_HINT
    return f"{_PROMPT_ENGINEER_BASE}\n{target_hint}\n{mode_hint}"


def parse_prompt_and_summary(raw: str) -> tuple[str, str]:
    """Разобрать ответ LLM формата ``PROMPT:`` / ``ОПИСАНИЕ:`` на (англ. промпт,
    рус. описание). Если формат не распознан — весь текст считаем промптом."""
    prompt, summary = "", ""
    for line in raw.splitlines():
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key_low = key.strip().lower()
        if key_low == "prompt":
            prompt = value.strip()
        elif key_low in ("описание", "summary"):
            summary = value.strip()
    if not prompt:
        prompt = raw.strip()
    return prompt, summary


class AgentPlatformAPIError(Exception):
    """Errors returned from the AgentPlatform API."""


class AgentPlatformClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        translate_model: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.translate_model = translate_model or model
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

    async def _chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature

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
        except TimeoutError as err:
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

    async def generate_song_text(self, *, prompt: str) -> str:
        if not prompt:
            raise AgentPlatformAPIError("Промпт для генерации текста пуст.")

        full_prompt = f"{prompt.strip()}\n\n{SONG_PROMPT_SUFFIX}"
        return await self._chat(
            messages=[{"role": "user", "content": full_prompt}],
        )

    async def translate_to_english(self, *, text: str, model: str | None = None) -> str:
        if not text or not text.strip():
            raise AgentPlatformAPIError("Текст для перевода пуст.")

        return await self._chat(
            messages=[
                {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
                {"role": "user", "content": text.strip()},
            ],
            model=model or self.translate_model,
            temperature=0,
        )

    async def generate_image_prompt(
        self,
        *,
        text: str,
        mode: str,
        target: str,
        model: str | None = None,
    ) -> tuple[str, str]:
        """Сгенерировать/обогатить промпт. Возвращает (англ. промпт, рус. описание).

        mode: ``enrich`` (обогатить черновик) | ``scratch`` (создать по теме).
        target: ``create`` (text2img) | ``edit`` (image-to-image)."""
        if not text or not text.strip():
            raise AgentPlatformAPIError("Пустой ввод для генерации промпта.")

        raw = await self._chat(
            messages=[
                {
                    "role": "system",
                    "content": build_image_prompt_system(mode=mode, target=target),
                },
                {"role": "user", "content": text.strip()},
            ],
            model=model or self.translate_model,
            temperature=0.9,
        )
        return parse_prompt_and_summary(raw)


def build_agent_platform_client() -> AgentPlatformClient:
    if not se.agent_platform.api_key:
        raise AgentPlatformAPIError("AGENT_PLATFORM_API_KEY не задан.")

    return AgentPlatformClient(
        api_key=se.agent_platform.api_key,
        base_url=se.agent_platform.base_url,
        model=se.agent_platform.model,
        translate_model=se.agent_platform.translate_model,
        timeout=se.agent_platform.timeout,
    )
