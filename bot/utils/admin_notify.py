from __future__ import annotations

import html
import logging
import traceback
from typing import Any

from aiogram import Bot

from bot.settings import se

logger = logging.getLogger(__name__)

_MAX_TB_LEN = 2800
_MAX_TEXT_LEN = 4000


async def notify_admins_error(
    bot: Bot,
    title: str,
    error: Exception,
    context: dict[str, Any] | None = None,
) -> None:
    if not se.admin_ids:
        return

    tb = traceback.format_exc()

    lines: list[str] = [f"<b>🚨 {html.escape(title)}</b>", ""]
    lines.append(
        f"<b>Тип:</b> <code>{html.escape(type(error).__name__)}</code>\n"
        f"<b>Сообщение:</b> <code>{html.escape(str(error)[:400])}</code>"
    )

    if context:
        lines.append("\n<b>Контекст:</b>")
        for key, val in context.items():
            lines.append(f"  • {html.escape(str(key))}: <code>{html.escape(str(val)[:300])}</code>")

    if tb and "NoneType: None" not in tb:
        short_tb = tb[-_MAX_TB_LEN:]
        lines.append(f"\n<b>Traceback:</b>\n<pre>{html.escape(short_tb)}</pre>")

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN]
        if text.count("<pre>") > text.count("</pre>"):
            text += "</pre>"
        text += "\n…"

    for admin_id in se.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception as exc:
            logger.warning("Не удалось отправить уведомление админу %s: %s", admin_id, exc)
