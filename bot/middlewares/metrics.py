from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.utils.metrics import metrics

logger = logging.getLogger(__name__)
SLOW_UPDATE_THRESHOLD = 1.0


class MetricsMiddleware(BaseMiddleware):
    async def __call__(  # type: ignore[override]
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start = time.perf_counter()
        metrics.inc("updates_total")
        try:
            result = await handler(event, data)
            metrics.inc("updates_success")
            return result
        except Exception:
            metrics.inc("updates_error")
            logger.exception("Ошибка обработки апдейта")
            raise
        finally:
            duration = time.perf_counter() - start
            if duration >= SLOW_UPDATE_THRESHOLD:
                metrics.inc("updates_slow")
                logger.warning(
                    "Медленная обработка апдейта: %.2f сек, тип=%s",
                    duration,
                    getattr(event, "event_type", type(event).__name__),
                )
