from __future__ import annotations

import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from redis.asyncio import Redis

from bot.db.enum import UserRole
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import MenuAction
from bot.keyboards.inline import ik_demo_result_cta
from bot.utils.image_models import DEFAULT_IMAGE_MODEL_KEY, get_image_model
from bot.utils.image_tasks import ImageGenerationError, generate_image

router = Router()
logger = logging.getLogger(__name__)

# Заглушка-демо-фото. Замени на курированное «вкусное» фото, чтобы демо
# давало настоящий «вау»-эффект (см. bot/assets/demo_placeholder.png).
DEMO_IMAGE_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "demo_placeholder.png"
)

# Заранее подобранный «крутой» промпт, дающий зрелищный результат в один тап.
DEMO_PROMPT = (
    "Преврати это фото в эффектную неоновую иллюстрацию в стиле киберпанк: "
    "кинематографический свет, насыщенные цвета, высокая детализация"
)

# Демо доступно один раз на пользователя (бесплатно). Флаг живёт долго —
# повторно демо не запускаем, отправляем к работе со своим фото.
_DEMO_FLAG_TTL = 60 * 60 * 24 * 90


def _demo_flag_key(user_id: int) -> str:
    return f"demo_used:{user_id}"


async def _load_demo_image() -> bytes:
    return DEMO_IMAGE_PATH.read_bytes()


@router.callback_query(MenuAction.filter(F.action == "demo_try"))
async def demo_try(
    query: CallbackQuery,
    user: UserRD,
    redis: Redis,
) -> None:
    await query.answer()
    # Демо пока в тестовом режиме — только для админов.
    if user.role != UserRole.ADMIN.value:
        await query.answer("Демо пока в тестовом режиме.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        return
    message = query.message

    # Один бесплатный демо-запуск на пользователя. Ставим флаг сразу (NX),
    # чтобы двойной тап не запускал две генерации.
    acquired = await redis.set(
        _demo_flag_key(user.user_id), b"1", nx=True, ex=_DEMO_FLAG_TTL
    )
    if not acquired:
        await message.answer(
            "✨ Демо вы уже попробовали!\n\n"
            "Теперь загрузите своё фото — результат будет ещё круче.",
            reply_markup=await ik_demo_result_cta(),
        )
        return

    status_msg = await message.answer(
        "🪄 Готовлю демо-результат… Это займёт несколько секунд."
    )

    model = get_image_model(DEFAULT_IMAGE_MODEL_KEY)
    positive_prompt = f"{model.prompt_prefix}{DEMO_PROMPT}".strip()

    try:
        demo_bytes = await _load_demo_image()
        image_bytes = await generate_image(
            prompt=positive_prompt,
            model=model.api_model,
            provider=model.provider,
            reference_images=[demo_bytes],
            aspect_ratio="1:1",
            output_format="jpeg",
            negative_prompt=model.negative_prompt or None,
            img2img_mode=model.img2img_mode,
            steps=model.steps,
            cfg_scale=model.cfg_scale,
        )
    except (ImageGenerationError, OSError) as exc:
        # Демо не прошло — снимаем флаг, чтобы пользователь мог попробовать снова.
        await redis.delete(_demo_flag_key(user.user_id))
        logger.warning("Демо-генерация не удалась: %s", exc)
        await status_msg.edit_text(
            "😔 Не получилось подготовить демо. Попробуйте позже или сразу "
            "загрузите своё фото.",
            reply_markup=await ik_demo_result_cta(),
        )
        return
    except Exception:
        await redis.delete(_demo_flag_key(user.user_id))
        logger.exception("Неожиданная ошибка демо-генерации")
        await status_msg.edit_text(
            "😔 Что-то пошло не так. Попробуйте позже или загрузите своё фото.",
            reply_markup=await ik_demo_result_cta(),
        )
        return

    if user.credits > 0:
        credits_line = (
            f"Загрузите снимок и опишите, что сделать — у вас на балансе "
            f"{user.credits} кредитов."
        )
    else:
        credits_line = (
            "Пополните баланс или пригласите друга — и обработайте своё фото."
        )

    await status_msg.delete()
    await message.answer_photo(
        photo=BufferedInputFile(file=image_bytes, filename="demo.jpg"),
        caption=(
            "🎉 <b>Вот что умеет бот — и это бесплатно, в один тап!</b>\n\n"
            "А теперь представьте, что так преобразится <b>ваше</b> фото 👇\n"
            f"{credits_line}"
        ),
        reply_markup=await ik_demo_result_cta(),
    )
