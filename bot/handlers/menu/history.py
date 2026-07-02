from __future__ import annotations

import json
import logging
import math
import uuid
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import GenerationKind, GenerationTaskStatus
from bot.db.models import GenerationTaskModel
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import GenHistoryAction, GenHistoryPage, MenuAction
from bot.utils.billing import (
    CreditsExhausted,
    GenerationBusy,
    enqueue_generation,
)
from bot.utils.image_models import get_image_model
from bot.utils.messaging import edit_or_answer
from bot.utils.video_models import get_kling_model, video_cost

router = Router()
logger = logging.getLogger(__name__)

PAGE_SIZE = 6
_PROMPT_SNIPPET = 60

_KIND_LABELS = {
    GenerationKind.IMAGE_EDIT.value: "🖌 Правка",
    GenerationKind.IMAGE_CREATE.value: "✨ Генерация",
    GenerationKind.VIDEO.value: "🎬 Видео",
}
_STATUS_LABELS = {
    GenerationTaskStatus.QUEUED.value: "⏳ В очереди",
    GenerationTaskStatus.PROCESSING.value: "⚙️ Выполняется",
    GenerationTaskStatus.SUCCESS.value: "✅ Готово",
    GenerationTaskStatus.ERROR.value: "⚠️ Ошибка",
    GenerationTaskStatus.REFUNDED.value: "↩️ Возврат",
}

EMPTY_TEXT = (
    "🗂 История генераций пуста.\n\n"
    "Создайте изображение или видео — и они появятся здесь."
)


def _model_title(kind: str, params: dict[str, Any]) -> str:
    model_key = str(params.get("model_key", ""))
    if kind == GenerationKind.VIDEO.value:
        return get_kling_model(model_key).title
    return get_image_model(model_key).title


def _repeat_cost(kind: str, params: dict[str, Any]) -> int:
    model_key = str(params.get("model_key", ""))
    if kind == GenerationKind.VIDEO.value:
        return video_cost(model_key, int(params.get("duration", 5)))
    return get_image_model(model_key).cost


def _parse_params(task: GenerationTaskModel) -> dict[str, Any]:
    try:
        data = json.loads(task.params or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _snippet(prompt: str) -> str:
    prompt = " ".join(prompt.split())
    if len(prompt) > _PROMPT_SNIPPET:
        return prompt[: _PROMPT_SNIPPET - 1].rstrip() + "…"
    return prompt or "—"


def _history_text(tasks: list[GenerationTaskModel], page: int, pages: int) -> str:
    lines = ["🗂 <b>История генераций</b>\n"]
    for idx, task in enumerate(tasks, start=1):
        params = _parse_params(task)
        kind = _KIND_LABELS.get(task.kind, task.kind)
        status = _STATUS_LABELS.get(task.status, task.status)
        when = task.created_at.strftime("%d.%m %H:%M") if task.created_at else "—"
        prompt = _snippet(str(params.get("prompt", "")))
        lines.append(
            f"{idx}. {kind} · {_model_title(task.kind, params)} · {status}\n"
            f"   <i>{when}</i> — {prompt}"
        )
    if pages > 1:
        lines.append(f"\nСтраница {page}/{pages}")
    return "\n".join(lines)


def _history_markup(
    tasks: list[GenerationTaskModel], page: int, pages: int
) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    # Кнопки повтора: по одной на задачу, компактно (номер соответствует списку).
    repeat_row: list[InlineKeyboardButton] = []
    for idx, task in enumerate(tasks, start=1):
        repeat_row.append(
            InlineKeyboardButton(
                text=f"🔁 {idx}",
                callback_data=GenHistoryAction(action="repeat", task_id=task.id).pack(),
            )
        )
    for i in range(0, len(repeat_row), 3):
        builder.row(*repeat_row[i : i + 3])

    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(
            InlineKeyboardButton(
                text="◀️", callback_data=GenHistoryPage(page=page - 1).pack()
            )
        )
    if page < pages:
        nav.append(
            InlineKeyboardButton(
                text="▶️", callback_data=GenHistoryPage(page=page + 1).pack()
            )
        )
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(
            text="🏠 Главное меню", callback_data=MenuAction(action="home").pack()
        )
    )
    return builder


async def _render_history(
    target: CallbackQuery | Message,
    user: UserRD,
    session: AsyncSession,
    *,
    page: int,
) -> None:
    total = await session.scalar(
        select(func.count(GenerationTaskModel.id)).where(
            GenerationTaskModel.user_idpk == user.id
        )
    )
    total = int(total or 0)
    if total == 0:
        if isinstance(target, CallbackQuery):
            await edit_or_answer(target, text=EMPTY_TEXT, reply_markup=None)
        else:
            await target.answer(EMPTY_TEXT)
        return

    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, pages))
    tasks = list(
        await session.scalars(
            select(GenerationTaskModel)
            .where(GenerationTaskModel.user_idpk == user.id)
            .order_by(GenerationTaskModel.created_at.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    )
    text = _history_text(tasks, page, pages)
    markup = _history_markup(tasks, page, pages).as_markup()
    if isinstance(target, CallbackQuery):
        await edit_or_answer(target, text=text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.message(Command("history"))
async def cmd_history(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await state.clear()
    await _render_history(message, user, session, page=1)


@router.callback_query(MenuAction.filter(F.action == "history"))
async def menu_history(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await query.answer()
    await state.clear()
    await _render_history(query, user, session, page=1)


@router.callback_query(GenHistoryPage.filter())
async def history_page(
    query: CallbackQuery,
    callback_data: GenHistoryPage,
    user: UserRD,
    session: AsyncSession,
) -> None:
    await query.answer()
    await _render_history(query, user, session, page=callback_data.page)


@router.callback_query(GenHistoryAction.filter(F.action == "repeat"))
async def history_repeat(
    query: CallbackQuery,
    callback_data: GenHistoryAction,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    # Скоуп по user.id: повторить можно только свою генерацию (без IDOR).
    task = await session.scalar(
        select(GenerationTaskModel).where(
            GenerationTaskModel.id == callback_data.task_id,
            GenerationTaskModel.user_idpk == user.id,
        )
    )
    if task is None:
        await query.answer("Генерация не найдена.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        return

    params = _parse_params(task)
    if not params.get("prompt") and task.kind != GenerationKind.VIDEO.value:
        await query.answer("Нет данных для повтора.", show_alert=True)
        return

    cost = _repeat_cost(task.kind, params)
    if user.credits < cost:
        await query.answer(
            f"Недостаточно кредитов. Нужно: {cost}, у вас: {user.credits}",
            show_alert=True,
        )
        return

    await query.answer("Повторяю генерацию…")
    display_id = uuid.uuid4().hex[:8]
    status_msg = await query.message.answer(
        f"🔁 Повтор генерации запущен!\n🆔 Задача: {display_id}\n"
        "Я пришлю результат, как только он будет готов."
    )

    try:
        await enqueue_generation(
            session=session,
            redis=redis,
            user=user,
            kind=task.kind,
            cost=cost,
            chat_id=query.message.chat.id,
            status_message_id=status_msg.message_id,
            params=params,
        )
    except GenerationBusy:
        await status_msg.edit_text(
            "⏳ Достигнут лимит одновременных генераций (3). "
            "Дождитесь завершения одной из них и попробуйте снова."
        )
    except CreditsExhausted:
        await status_msg.edit_text(f"Недостаточно кредитов. Нужно: {cost}.")
    except Exception:
        logger.exception("Не удалось повторить генерацию из истории")
        await status_msg.edit_text(
            "❌ Не удалось запустить повтор. Попробуйте ещё раз."
        )
