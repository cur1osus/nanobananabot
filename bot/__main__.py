from __future__ import annotations

import asyncio
import logging
from asyncio import CancelledError
from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

import msgspec
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BotCommand
from dotenv import load_dotenv
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import handlers
from bot.background_tasks import schedule_music_polling
from bot.db.base import close_db, create_db_session_pool, init_db
from bot.middlewares.metrics import MetricsMiddleware
from bot.middlewares.throw_session import ThrowDBSessionMiddleware
from bot.middlewares.throw_user_model import ThrowUserMiddleware
from bot.scheduler import default_scheduler as scheduler
from bot.scheduler import logger as scheduler_logger
from bot.settings import Settings, se
from bot.utils.texts import BOT_DESCRIPTION_TEXT, BOT_INFO_TEXT

load_dotenv()

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
SHORT_DESCRIPTION_LIMIT = 120


def _moscow_converter(timestamp: float) -> tuple:
    return datetime.fromtimestamp(timestamp, MOSCOW_TZ).timetuple()


class MoscowFormatter(logging.Formatter):
    converter = staticmethod(_moscow_converter)


def setup_logging() -> None:
    formatter = MoscowFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)


scheduler_logger.setLevel(logging.ERROR)
setup_logging()
logger = logging.getLogger(__name__)


async def start_scheduler(
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    bot: Bot,
) -> None:
    schedule_music_polling(
        bot=bot,
        sessionmaker=sessionmaker,
        redis=redis,
    )
    while True:
        await scheduler.run_pending()
        await asyncio.sleep(1)


async def startup(dispatcher: Dispatcher, bot: Bot, se: Settings, redis: Redis) -> None:
    await bot.delete_webhook(drop_pending_updates=True)

    engine, db_session = await create_db_session_pool(se)
    await init_db(engine)

    dispatcher.workflow_data.update(
        {
            "sessionmaker": db_session,
            "db_session_closer": partial(close_db, engine),
            "redis": redis,
        }
    )

    dispatcher.update.outer_middleware(MetricsMiddleware())
    dispatcher.update.outer_middleware(ThrowDBSessionMiddleware())
    dispatcher.update.outer_middleware(ThrowUserMiddleware())

    asyncio.create_task(
        start_scheduler(
            sessionmaker=db_session,
            redis=redis,
            bot=bot,
        )
    )

    logger.info("Бот запущен")


async def shutdown(dispatcher: Dispatcher) -> None:
    await dispatcher["db_session_closer"]()
    logger.info("Бот остановлен")


async def set_default_commands(bot: Bot, max_retries: int = 3) -> None:
    """Установка команд и профиля бота с обработкой RetryAfter."""
    for attempt in range(max_retries):
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="start"),
                ]
            )
            await _set_bot_profile(bot)
            logger.info("Команды и профиль бота успешно установлены")
            return
        except TelegramRetryAfter as e:
            retry_after = e.retry_after
            logger.warning(
                f"RetryAfter при установке команд: ждём {retry_after} сек (попытка {attempt + 1}/{max_retries})"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_after)
            else:
                logger.error("Не удалось установить команды после всех попыток")
                raise
        except Exception as e:
            logger.error(f"Ошибка при установке команд: {e}", exc_info=True)
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2)


async def _set_bot_profile(bot: Bot) -> None:
    short_description = _short_description_text()
    await bot.set_my_short_description(short_description=short_description)
    await bot.set_my_description(description=BOT_DESCRIPTION_TEXT)


def _short_description_text() -> str:
    if len(BOT_INFO_TEXT) <= SHORT_DESCRIPTION_LIMIT:
        return BOT_INFO_TEXT
    lines: list[str] = []
    current_len = 0
    for line in BOT_INFO_TEXT.splitlines():
        line = line.strip()
        if not line:
            continue
        extra_len = len(line) + (1 if lines else 0)
        if current_len + extra_len > SHORT_DESCRIPTION_LIMIT:
            break
        lines.append(line)
        current_len += extra_len
    if lines:
        return "\n".join(lines)
    first_line = BOT_INFO_TEXT.splitlines()[0].strip()
    return first_line[:SHORT_DESCRIPTION_LIMIT]


async def main() -> None:
    if not se.suno.api_key:
        raise RuntimeError("SUNO_API_KEY не задан. Бот не может быть запущен.")

    api = PRODUCTION

    bot = Bot(
        token=se.bot_token,
        session=AiohttpSession(api=api),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    redis = await se.redis_dsn()
    storage = RedisStorage(
        redis=redis,
        key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
        json_loads=msgspec.json.decode,
        json_dumps=partial(lambda obj: str(msgspec.json.encode(obj), encoding="utf-8")),
    )

    dp = Dispatcher(
        storage=storage,
        events_isolation=SimpleEventIsolation(),
    )

    dp.include_routers(handlers.router)
    dp.startup.register(partial(startup, se=se, redis=redis))
    dp.shutdown.register(shutdown)

    if se.set_commands_on_startup:
        await set_default_commands(bot)
    else:
        logger.info("Установка команд отключена (SET_COMMANDS_ON_STARTUP=false)")

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        uvloop = __import__("uvloop")
        loop_factory = uvloop.new_event_loop

    except ModuleNotFoundError:
        loop_factory = asyncio.new_event_loop
        logger.info("uvloop не найден, используется стандартный цикл событий")

    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            runner.run(main())

    except (CancelledError, KeyboardInterrupt):
        __import__("sys").exit(0)
