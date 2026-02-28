import os

from dotenv import load_dotenv
from redis.asyncio import Redis
from sqlalchemy import URL

load_dotenv()


def _parse_int_list(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        value = part.strip()
        if value.isdigit():
            ids.append(int(value))
    return ids


class RedisSettings:
    def __init__(self) -> None:
        self.host = os.environ.get("REDIS_HOST", "localhost")
        self.port = int(os.environ.get("REDIS_PORT", 6379))
        self.db = os.environ.get("REDIS_DB", 0)


class DBSettings:
    def __init__(self, _env_prefix: str = "MYSQL_") -> None:
        self.host = os.environ.get(f"{_env_prefix}HOST", "localhost")
        self.port = os.environ.get(f"{_env_prefix}PORT", 3306)
        self.db = os.environ.get(f"{_env_prefix}DB", "database")
        self.username = os.environ.get(f"{_env_prefix}USERNAME", "user")
        self.password = os.environ.get(f"{_env_prefix}PASSWORD", "password")


class SunoSettings:
    def __init__(self) -> None:
        self.api_key = os.environ.get("SUNO_API_KEY", "")
        self.model = os.environ.get("SUNO_MODEL", "V5")
        self.callback_url = os.environ.get(
            "SUNO_CALLBACK_URL",
            "https://example.com/callback",
        )
        self.poll_interval = float(os.environ.get("SUNO_POLL_INTERVAL", 5))
        self.poll_timeout = int(os.environ.get("SUNO_POLL_TIMEOUT", 120))


class AgentPlatformSettings:
    def __init__(self) -> None:
        self.api_key = os.environ.get("AGENT_PLATFORM_API_KEY", "")
        self.base_url = os.environ.get(
            "AGENT_PLATFORM_BASE_URL",
            "https://litellm.tokengate.ru/v1",
        )
        self.model = os.environ.get(
            "AGENT_PLATFORM_MODEL",
            "cloudru/openai/gpt-oss-120b",
        )
        self.timeout = int(os.environ.get("AGENT_PLATFORM_TIMEOUT", 60))


class VseGptSettings:
    def __init__(self) -> None:
        self.api_key = os.environ.get("VSEGPT_API_KEY", "")
        self.base_url = os.environ.get(
            "VSEGPT_BASE_URL",
            "https://api.vsegpt.ru/v1",
        )
        self.stt_model = os.environ.get(
            "VSEGPT_STT_MODEL",
            "stt-openai/whisper-1",
        )
        self.timeout = int(os.environ.get("VSEGPT_TIMEOUT", 60))


class WithdrawSettings:
    def __init__(self) -> None:
        raw_ids = os.environ.get("WITHDRAW_MANAGER_IDS", "")
        self.manager_ids = _parse_int_list(raw_ids)


class PaymentsSettings:
    def __init__(self) -> None:
        self.yookassa_provider_token = os.environ.get(
            "YOOKASSA_PROVIDER_TOKEN",
            "",
        )
        self.yookassa_tax_system_code = int(
            os.environ.get("YOOKASSA_TAX_SYSTEM_CODE", "1")
        )
        self.yookassa_vat_code = int(os.environ.get("YOOKASSA_VAT_CODE", "1"))
        self.yookassa_payment_mode = os.environ.get(
            "YOOKASSA_PAYMENT_MODE",
            "full_payment",
        )
        self.yookassa_payment_subject = os.environ.get(
            "YOOKASSA_PAYMENT_SUBJECT",
            "commodity",
        )


class TopupSettings:
    def __init__(self) -> None:
        self.tariffs_card_raw = os.environ.get(
            "TOPUP_TARIFFS_CARD",
            "10:10:6:3,20:20:20:10,30:30:50:25,40:40:120:60",
        )
        self.tariffs_stars_raw = os.environ.get(
            "TOPUP_TARIFFS_STARS",
            "1:1:6:3,2:2:20:10,3:3:50:25,4:4:120:60",
        )


class Settings:
    bot_token = os.environ.get("BOT_TOKEN", "")
    sep = os.environ.get("SEP", "\n")
    set_commands_on_startup = os.environ.get(
        "SET_COMMANDS_ON_STARTUP", "true"
    ).lower() in ("true", "1", "yes")

    db: DBSettings = DBSettings()
    redis: RedisSettings = RedisSettings()
    suno: SunoSettings = SunoSettings()
    agent_platform: AgentPlatformSettings = AgentPlatformSettings()
    vsegpt: VseGptSettings = VseGptSettings()
    withdraw: WithdrawSettings = WithdrawSettings()
    payments: PaymentsSettings = PaymentsSettings()
    topup: TopupSettings = TopupSettings()

    def mysql_dsn(self) -> URL:
        return URL.create(
            drivername="mysql+aiomysql",
            database=self.db.db,
            username=self.db.username,
            password=self.db.password,
            host=self.db.host,
        )

    def mysql_dsn_string(self) -> str:
        return URL.create(
            drivername="mysql+aiomysql",
            database=self.db.db,
            username=self.db.username,
            password=self.db.password,
            host=self.db.host,
        ).render_as_string(hide_password=False)

    async def redis_dsn(self) -> Redis:
        return Redis(host=self.redis.host, port=self.redis.port, db=self.redis.db)


se = Settings()
