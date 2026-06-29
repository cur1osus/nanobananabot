from __future__ import annotations

from typing import Annotated

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy import URL

load_dotenv()


def _parse_int_list(raw: object) -> list[int]:
    """Разобрать список целых из строки ``"1, 2, 3"`` или готового списка.

    Нечисловые элементы игнорируются — поведение исторического парсера ENV.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [int(value) for value in raw]
    ids: list[int] = []
    for part in str(raw).split(","):
        value = part.strip()
        if value.isdigit():
            ids.append(int(value))
    return ids


# Список ID из ENV приходит как "1,2,3" — NoDecode отключает JSON-парсинг
# pydantic-settings, а валидатор разбирает CSV вручную.
IntList = Annotated[list[int], NoDecode]


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    db: int = 0


class DBSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYSQL_", extra="ignore")

    host: str = "localhost"
    port: int = 3306
    db: str = "database"
    username: str = "user"
    password: str = "password"


class ImageBackendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMAGE_BACKEND_", extra="ignore", protected_namespaces=()
    )

    provider: str = "runware"
    api_key: str = ""
    base_url: str = "https://api.runware.ai/v1"
    model: str = "google:4@1"
    timeout: int = 120
    total_timeout: int = 150
    retries: int = 1
    retry_backoff: float = 2
    rate_limit_retries: int = 3
    rate_limit_backoff: float = 1

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> str:
        return str(value).strip().lower()

    @field_validator("total_timeout")
    @classmethod
    def _min_total_timeout(cls, value: int) -> int:
        return max(1, value)

    @field_validator("retries", "rate_limit_retries")
    @classmethod
    def _non_negative_int(cls, value: int) -> int:
        return max(0, value)

    @field_validator("retry_backoff", "rate_limit_backoff")
    @classmethod
    def _non_negative_float(cls, value: float) -> float:
        return max(0.0, value)


class ProdiaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRODIA_", extra="ignore")

    api_token: str = ""
    base_url: str = "https://inference.prodia.com"
    timeout: int = 120
    total_timeout: int = 180
    rate_limit_retries: int = 3
    rate_limit_backoff: float = 2

    @field_validator("base_url", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, value: object) -> str:
        return str(value).rstrip("/")

    @field_validator("total_timeout")
    @classmethod
    def _min_total_timeout(cls, value: int) -> int:
        return max(1, value)

    @field_validator("rate_limit_retries")
    @classmethod
    def _non_negative_int(cls, value: int) -> int:
        return max(0, value)

    @field_validator("rate_limit_backoff")
    @classmethod
    def _non_negative_float(cls, value: float) -> float:
        return max(0.0, value)


class SunoSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUNO_", extra="ignore", protected_namespaces=()
    )

    api_key: str = ""
    model: str = "V5"
    callback_url: str = "https://example.com/callback"
    poll_interval: float = 5
    poll_timeout: int = 120


class AgentPlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_PLATFORM_", extra="ignore", protected_namespaces=()
    )

    api_key: str = ""
    base_url: str = "https://litellm.tokengate.ru/v1"
    model: str = "cloudru/openai/gpt-oss-120b"
    # Дешёвая быстрая модель для перевода промптов на английский (флэш-класс).
    translate_model: str = "google/gemini-3-flash-preview"
    timeout: int = 60


class VseGptSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VSEGPT_", extra="ignore")

    api_key: str = ""
    base_url: str = "https://api.vsegpt.ru/v1"
    stt_model: str = "stt-openai/whisper-1"
    timeout: int = 60


class WithdrawSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WITHDRAW_", extra="ignore")

    manager_ids: IntList = Field(default_factory=list)

    @field_validator("manager_ids", mode="before")
    @classmethod
    def _parse_manager_ids(cls, value: object) -> list[int]:
        return _parse_int_list(value)


class PaymentsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    yookassa_provider_token: str = Field("", validation_alias="YOOKASSA_PROVIDER_TOKEN")
    yookassa_tax_system_code: int = Field(
        1, validation_alias="YOOKASSA_TAX_SYSTEM_CODE"
    )
    yookassa_vat_code: int = Field(1, validation_alias="YOOKASSA_VAT_CODE")
    yookassa_payment_mode: str = Field(
        "full_payment", validation_alias="YOOKASSA_PAYMENT_MODE"
    )
    yookassa_payment_subject: str = Field(
        "commodity", validation_alias="YOOKASSA_PAYMENT_SUBJECT"
    )


class CivitaiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CIVITAI_", extra="ignore", protected_namespaces=()
    )

    api_key: str = ""
    base_url: str = "https://orchestration.civitai.com"
    timeout: int = 120
    total_timeout: int = 600


class TopupSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    tariffs_card_raw: str = Field(
        "99:99:30:30,199:199:65:65,499:499:170:170,799:799:270:270,1499:1499:540:540",
        validation_alias="TOPUP_TARIFFS_CARD",
    )
    tariffs_stars_raw: str = Field(
        "1:1:6:3,2:2:20:10,3:3:50:25,4:4:120:60",
        validation_alias="TOPUP_TARIFFS_STARS",
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    bot_token: str = Field("", validation_alias="BOT_TOKEN")
    sep: str = Field("\n", validation_alias="SEP")
    admin_ids: IntList = Field(default_factory=list, validation_alias="ADMIN_IDS")
    set_commands_on_startup: bool = Field(
        True, validation_alias="SET_COMMANDS_ON_STARTUP"
    )

    db: DBSettings = Field(default_factory=DBSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    image_backend: ImageBackendSettings = Field(default_factory=ImageBackendSettings)
    prodia: ProdiaSettings = Field(default_factory=ProdiaSettings)
    suno: SunoSettings = Field(default_factory=SunoSettings)
    agent_platform: AgentPlatformSettings = Field(default_factory=AgentPlatformSettings)
    vsegpt: VseGptSettings = Field(default_factory=VseGptSettings)
    withdraw: WithdrawSettings = Field(default_factory=WithdrawSettings)
    payments: PaymentsSettings = Field(default_factory=PaymentsSettings)
    topup: TopupSettings = Field(default_factory=TopupSettings)
    civitai: CivitaiSettings = Field(default_factory=CivitaiSettings)

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        return _parse_int_list(value)

    def mysql_dsn(self) -> URL:
        return URL.create(
            drivername="mysql+aiomysql",
            database=self.db.db,
            username=self.db.username,
            password=self.db.password,
            host=self.db.host,
            port=int(self.db.port),
        )

    def mysql_dsn_string(self) -> str:
        return self.mysql_dsn().render_as_string(hide_password=False)

    async def redis_dsn(self) -> Redis:
        return Redis(host=self.redis.host, port=self.redis.port, db=self.redis.db)

    def validate_required(self) -> None:
        """Проверить критичные настройки и упасть с понятной ошибкой.

        Лучше остановиться на старте с явным списком отсутствующих переменных,
        чем падать позже в рантайме на первом обращении к Telegram/БД.
        """
        missing: list[str] = []
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.db.username or not self.db.password or not self.db.db:
            missing.append("MYSQL_USERNAME/MYSQL_PASSWORD/MYSQL_DB")
        if missing:
            raise RuntimeError(
                "Не заданы обязательные переменные окружения: " + ", ".join(missing)
            )


se = Settings()
