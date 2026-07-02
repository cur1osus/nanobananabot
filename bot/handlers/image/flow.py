from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enum import GenerationKind
from bot.db.redis.user_model import UserRD
from bot.keyboards.factories import (
    AiPrompt,
    CreateAspectRatio,
    ImageNav,
    ImageResultAction,
    ModelGroupSwitch,
    ModelMenu,
    ModelSelect,
    SelectScenario,
)
from bot.keyboards.inline import (
    ik_ai_prompt_input_back,
    ik_ai_prompt_modes,
    ik_ai_prompt_result,
    ik_back_home,
    ik_create_aspect_ratio,
    ik_create_prompt_nav,
    ik_image_model_select,
    ik_image_waiting_photos,
    ik_model_select_for_key,
    ik_other_image_model_select,
    ik_prompt_nav,
    ik_scenario_select,
)
from bot.states import BaseUserState, ImageGenerationState
from bot.utils.image_models import (
    DEFAULT_IMAGE_MODEL_KEY,
    get_image_model,
    is_adult_model_key,
    is_image_model_key,
)
from bot.utils.image_state import get_image_data, update_image_data
from bot.utils.image_tasks import closest_aspect_ratio
from bot.utils.billing import (
    CreditsExhausted,
    GenerationBusy,
    enqueue_generation,
)
from bot.utils.messaging import edit_or_answer
from bot.utils.speech_recognition import (
    SpeechRecognitionError,
    transcribe_message_audio,
)
from bot.utils.agent_platform import build_agent_platform_client
from bot.utils.texts import (
    ADULT_CREATE_PROMPT_TEXT,
    ADULT_PROMPT_REQUEST_TEXT,
    AI_PROMPT_ENRICH_ASK,
    AI_PROMPT_MODE_TEXT,
    AI_PROMPT_SCRATCH_ASK,
    CREATE_ASPECT_RATIO_TEXT,
    CREATE_PROMPT_TEXT,
    PROMPT_REQUEST_TEXT,
    ai_prompt_result_text,
    generation_started_text,
    model_panel_text,
)

AI_PROMPT_STATE_KEY = "ai_prompt"

router = Router()
logger = logging.getLogger(__name__)

DEFAULT_MAX_REFERENCES = 4
NANO2_MAX_REFERENCES = 8
GPT_IMAGE_2_MAX_REFERENCES = 16

CREATE_RATIO_MAP: dict[str, str] = {
    "auto": "auto",
    "21x9": "21:9",
    "16x9": "16:9",
    "3x2": "3:2",
    "4x3": "4:3",
    "5x4": "5:4",
    "1x1": "1:1",
    "4x5": "4:5",
    "3x4": "3:4",
    "2x3": "2:3",
    "9x16": "9:16",
}


def _photo_limit_for_model(model_key: str) -> int:
    if model_key == "gpt_image_2":
        return GPT_IMAGE_2_MAX_REFERENCES
    if model_key == "nano2":
        return NANO2_MAX_REFERENCES
    return DEFAULT_MAX_REFERENCES


def _photo_request_text(model_key: str) -> str:
    max_refs = _photo_limit_for_model(model_key)
    return f"Пришлите 1-{max_refs} фотографий которые нужно изменить или объединить"


async def _run_image_generation(
    *,
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
    prompt: str,
    strength: float | None = None,
    scenario_steps: int | None = None,
) -> None:
    """Поставить генерацию-редактирование в очередь и сразу освободить чат.

    Тяжёлая работа (скачивание референсов, вызов провайдера, доставка) делается
    воркером (см. bot/utils/generation_runner.py), поэтому хендлер не держит
    per-user изоляцию событий и пользователь может продолжать пользоваться ботом.
    """
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        await message.answer("Опишите запрос текстом.")
        return

    data = await get_image_data(state)
    if not data.photos:
        await state.set_state(ImageGenerationState.waiting_photos)
        await message.answer(_photo_request_text(data.model_key))
        return

    model = get_image_model(data.model_key)
    if user.credits < model.cost:
        await message.answer(
            f"Недостаточно кредитов для генерации. Нужно: {model.cost}, у вас: {user.credits}",
            reply_markup=await ik_back_home(),
        )
        await state.set_state(ImageGenerationState.waiting_photos)
        return

    display_id = uuid.uuid4().hex[:8]
    status_msg = await message.answer(
        generation_started_text(display_id, data.model_key)
    )

    try:
        await enqueue_generation(
            session=session,
            redis=redis,
            user=user,
            kind=GenerationKind.IMAGE_EDIT.value,
            cost=model.cost,
            chat_id=message.chat.id,
            status_message_id=status_msg.message_id,
            params={
                "model_key": data.model_key,
                "prompt": normalized_prompt,
                "aspect_ratio": data.aspect_ratio,
                "photos": list(data.photos),
                "strength": strength,
                "steps": scenario_steps,
            },
        )
    except GenerationBusy:
        await status_msg.edit_text(
            "⏳ Достигнут лимит одновременных генераций (3). Дождитесь завершения одной из них и попробуйте снова."
        )
        return
    except CreditsExhausted:
        await status_msg.edit_text(
            f"Недостаточно кредитов для генерации. Нужно: {model.cost}."
        )
        return
    except Exception:
        logger.exception("Не удалось поставить генерацию-редактирование в очередь")
        await status_msg.edit_text(
            "❌ Не удалось запустить генерацию. Попробуйте ещё раз."
        )
        return

    await update_image_data(
        state,
        prompt=normalized_prompt,
        prompt_requested=True,
    )
    await state.set_state(ImageGenerationState.waiting_prompt)


async def _run_create_generation(
    *,
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
    prompt: str,
) -> None:
    """Поставить генерацию-создание (text-to-image) в очередь, не блокируя чат."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        await message.answer("Опишите запрос текстом.")
        return

    data = await get_image_data(state)
    model = get_image_model(data.model_key)
    if user.credits < model.cost:
        await message.answer(
            f"Недостаточно кредитов для генерации. Нужно: {model.cost}, у вас: {user.credits}",
            reply_markup=await ik_back_home(),
        )
        return

    display_id = uuid.uuid4().hex[:8]
    status_msg = await message.answer(
        generation_started_text(display_id, data.model_key)
    )

    try:
        await enqueue_generation(
            session=session,
            redis=redis,
            user=user,
            kind=GenerationKind.IMAGE_CREATE.value,
            cost=model.cost,
            chat_id=message.chat.id,
            status_message_id=status_msg.message_id,
            params={
                "model_key": data.model_key,
                "prompt": normalized_prompt,
                "aspect_ratio": data.aspect_ratio,
            },
        )
    except GenerationBusy:
        await status_msg.edit_text(
            "⏳ Достигнут лимит одновременных генераций (3). Дождитесь завершения одной из них и попробуйте снова."
        )
        return
    except CreditsExhausted:
        await status_msg.edit_text(
            f"Недостаточно кредитов для генерации. Нужно: {model.cost}."
        )
        return
    except Exception:
        logger.exception("Не удалось поставить генерацию-создание в очередь")
        await status_msg.edit_text(
            "❌ Не удалось запустить генерацию. Попробуйте ещё раз."
        )
        return

    await update_image_data(
        state,
        prompt=normalized_prompt,
        photos=[],
        prompt_requested=True,
    )
    await state.set_state(ImageGenerationState.waiting_create_prompt)


@router.callback_query(ModelMenu.filter())
async def open_model_menu(
    query: CallbackQuery,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await edit_or_answer(
        query,
        text=model_panel_text(user, selected_key),
        reply_markup=await ik_model_select_for_key(selected_key),
    )


@router.callback_query(ModelGroupSwitch.filter())
async def switch_model_group(
    query: CallbackQuery,
    callback_data: ModelGroupSwitch,
    state: FSMContext,
    user: UserRD,
) -> None:
    await query.answer()
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    if callback_data.group == "other":
        markup = await ik_other_image_model_select(selected_key)
    else:
        markup = await ik_image_model_select(selected_key)
    await edit_or_answer(
        query,
        text=model_panel_text(user, selected_key),
        reply_markup=markup,
    )


@router.callback_query(ModelSelect.filter())
async def select_model(
    query: CallbackQuery,
    callback_data: ModelSelect,
    state: FSMContext,
    user: UserRD,
) -> None:
    if not is_image_model_key(callback_data.model):
        await query.answer("Неизвестная модель", show_alert=True)
        return

    model = get_image_model(callback_data.model)
    if user.credits < model.cost:
        await query.answer(
            f"Недостаточно кредитов. Нужно: {model.cost}, у вас: {user.credits}",
            show_alert=True,
        )
        return

    current_state = await state.get_state()

    await update_image_data(
        state,
        model_key=callback_data.model,
        photos=[],
        aspect_ratio="auto",
        prompt="",
        prompt_requested=False,
    )

    if current_state == ImageGenerationState.waiting_create_model.state:
        await state.set_state(ImageGenerationState.waiting_create_aspect)
        await edit_or_answer(
            query,
            text=CREATE_ASPECT_RATIO_TEXT,
            reply_markup=await ik_create_aspect_ratio(),
        )
    else:
        await state.set_state(ImageGenerationState.waiting_photos)
        await edit_or_answer(
            query,
            text=(
                f"{model_panel_text(user, callback_data.model)}\n\n"
                f"{_photo_request_text(callback_data.model)}"
            ),
            reply_markup=await ik_image_waiting_photos(),
        )
    await query.answer()


@router.message(ImageGenerationState.waiting_create_model)
async def remind_create_model(
    message: Message,
    state: FSMContext,
    user: UserRD,
) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    await message.answer(
        model_panel_text(user, selected_key),
        reply_markup=await ik_model_select_for_key(selected_key),
    )


@router.message(ImageGenerationState.waiting_photos, F.text)
async def remind_photos(
    message: Message,
    state: FSMContext,
) -> None:
    data = await get_image_data(state)
    await message.answer(
        _photo_request_text(data.model_key),
        reply_markup=await ik_image_waiting_photos(is_adult_model_key(data.model_key)),
    )


@router.callback_query(ImageNav.filter())
async def handle_image_nav(
    query: CallbackQuery,
    callback_data: ImageNav,
    state: FSMContext,
    user: UserRD,
) -> None:
    data = await get_image_data(state)
    selected_key = data.model_key or DEFAULT_IMAGE_MODEL_KEY
    is_adult = is_adult_model_key(selected_key)

    if callback_data.action == "to_photos":
        await state.set_state(ImageGenerationState.waiting_photos)
        await query.answer()
        await edit_or_answer(
            query,
            text=_photo_request_text(selected_key),
            reply_markup=await ik_image_waiting_photos(is_adult),
        )
        return

    if callback_data.action == "to_create_aspect":
        await state.set_state(ImageGenerationState.waiting_create_aspect)
        await query.answer()
        await edit_or_answer(
            query,
            text=CREATE_ASPECT_RATIO_TEXT,
            reply_markup=await ik_create_aspect_ratio(is_adult),
        )
        return

    if callback_data.action == "to_prompt":
        await state.set_state(ImageGenerationState.waiting_prompt)
        await query.answer()
        prompt_text = ADULT_PROMPT_REQUEST_TEXT if is_adult else PROMPT_REQUEST_TEXT
        await edit_or_answer(
            query,
            text=prompt_text,
            reply_markup=await ik_prompt_nav(is_adult=is_adult),
        )
        return

    await query.answer("Неизвестное действие", show_alert=True)


@router.callback_query(ImageResultAction.filter())
async def handle_result_actions(
    query: CallbackQuery,
    callback_data: ImageResultAction,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    data = await get_image_data(state)

    if callback_data.action == "similar":
        if not data.photos or not data.prompt:
            await query.answer("Нет данных прошлой генерации", show_alert=True)
            return
        await query.answer()
        if isinstance(query.message, Message):
            await _run_image_generation(
                message=query.message,
                state=state,
                user=user,
                session=session,
                redis=redis,
                prompt=data.prompt,
            )
        return

    if callback_data.action == "keep_photos":
        if not data.photos:
            await query.answer("Нет сохраненных фото", show_alert=True)
            return
        await update_image_data(
            state,
            photos=list(data.photos),
            prompt="",
            prompt_requested=True,
        )
        await state.set_state(ImageGenerationState.waiting_prompt)
        await query.answer()
        if isinstance(query.message, Message):
            count = len(data.photos)
            kept = "фото" if count == 1 else f"фото ({count} шт.)"
            await query.message.answer(
                f"Оставил те же {kept}. Теперь пришлите новый промпт."
            )
        return

    if callback_data.action == "restart":
        await update_image_data(
            state,
            photos=[],
            prompt="",
            prompt_requested=False,
            aspect_ratio="auto",
        )
        await state.set_state(ImageGenerationState.waiting_photos)
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.answer(
                _photo_request_text(data.model_key),
                reply_markup=await ik_image_waiting_photos(
                    is_adult_model_key(data.model_key)
                ),
            )
        return

    await query.answer("Неизвестное действие", show_alert=True)


@router.callback_query(SelectScenario.filter())
async def handle_scenario_select(
    query: CallbackQuery,
    callback_data: SelectScenario,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    if callback_data.action == "select":
        if not callback_data.key:
            await query.answer()
            await edit_or_answer(
                query,
                text="Выберите сценарий:",
                reply_markup=await ik_scenario_select(),
            )
            return

        from bot.utils.image_scenarios import EDIT_SCENARIOS

        for sc in EDIT_SCENARIOS:
            if sc.key == callback_data.key:
                await query.answer()
                await query.message.delete()
                if isinstance(query.message, Message):
                    await _run_image_generation(
                        message=query.message,
                        state=state,
                        user=user,
                        session=session,
                        redis=redis,
                        prompt=sc.prompt,
                        strength=sc.strength,
                        scenario_steps=sc.steps,
                    )
                return
        await query.answer("Неизвестный сценарий", show_alert=True)
        return

    await query.answer()


@router.message(ImageGenerationState.waiting_photos, F.photo)
@router.message(ImageGenerationState.waiting_prompt, F.photo)
@router.message(
    ImageGenerationState.waiting_photos,
    F.document,
    F.document.mime_type.startswith("image/"),
)
@router.message(
    ImageGenerationState.waiting_prompt,
    F.document,
    F.document.mime_type.startswith("image/"),
)
async def collect_photos(
    message: Message,
    state: FSMContext,
) -> None:
    data = await get_image_data(state)
    photos = list(data.photos)
    max_references = _photo_limit_for_model(data.model_key)
    if len(photos) >= max_references:
        await message.answer(f"Можно отправить максимум {max_references} фото.")
        return
    width: int | None
    height: int | None
    if message.photo:
        photo_size = message.photo[-1]
        file_id = photo_size.file_id
        width, height = photo_size.width, photo_size.height
    elif message.document:
        file_id = message.document.file_id
        thumb = message.document.thumbnail
        width, height = (thumb.width, thumb.height) if thumb else (None, None)
    else:
        return
    photos.append(file_id)
    aspect_ratio = data.aspect_ratio
    if len(photos) == 1 and width and height:
        aspect_ratio = closest_aspect_ratio(width, height)

    prompt_requested = data.prompt_requested
    if not prompt_requested:
        prompt_requested = True
        prompt_text = (
            ADULT_PROMPT_REQUEST_TEXT
            if is_adult_model_key(data.model_key)
            else PROMPT_REQUEST_TEXT
        )
        await message.answer(
            prompt_text,
            reply_markup=await ik_prompt_nav(
                is_adult=is_adult_model_key(data.model_key)
            ),
        )
        await state.set_state(ImageGenerationState.waiting_prompt)

    await update_image_data(
        state,
        photos=photos,
        aspect_ratio=aspect_ratio,
        prompt_requested=prompt_requested,
    )

    if len(photos) >= max_references:
        await message.answer(
            f"Получено {max_references} фото. Теперь пришлите текстовый промпт."
        )


@router.message(ImageGenerationState.waiting_prompt, F.text)
async def collect_prompt(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    await _run_image_generation(
        message=message,
        state=state,
        user=user,
        session=session,
        redis=redis,
        prompt=message.text or "",
    )


@router.message(ImageGenerationState.waiting_prompt, F.voice | F.audio)
async def collect_prompt_voice(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    """Handle voice/audio messages for image generation prompt."""
    # Send processing message
    processing_msg = await message.answer("🎙️ Распознаю голосовое сообщение...")

    try:
        # Transcribe audio
        prompt = await transcribe_message_audio(message, language="ru")

        if not prompt:
            await processing_msg.edit_text(
                "Не удалось распознать голосовое сообщение. Попробуйте еще раз или введите текстом."
            )
            return

        # Delete processing message
        await processing_msg.delete()

        # Show recognized text
        await message.answer(f"📝 Распознано: {prompt}")

        await _run_image_generation(
            message=message,
            state=state,
            user=user,
            session=session,
            redis=redis,
            prompt=prompt,
        )

    except SpeechRecognitionError as e:
        await processing_msg.edit_text(
            f"❌ Ошибка распознавания: {e}\n\nПопробуйте ввести текстом."
        )
    except Exception:
        await processing_msg.edit_text(
            "❌ Произошла ошибка при обработке голосового сообщения. Попробуйте ввести текстом."
        )


@router.message(ImageGenerationState.waiting_create_aspect)
async def remind_create_aspect(message: Message, state: FSMContext) -> None:
    data = await get_image_data(state)
    await message.answer(
        "Выберите соотношение сторон кнопками ниже.",
        reply_markup=await ik_create_aspect_ratio(is_adult_model_key(data.model_key)),
    )


@router.callback_query(
    ImageGenerationState.waiting_create_aspect, CreateAspectRatio.filter()
)
async def select_create_aspect_ratio(
    query: CallbackQuery,
    callback_data: CreateAspectRatio,
    state: FSMContext,
) -> None:
    aspect_ratio = CREATE_RATIO_MAP.get(callback_data.ratio)
    if not aspect_ratio:
        await query.answer("Неизвестное соотношение", show_alert=True)
        return

    data = await update_image_data(
        state,
        photos=[],
        prompt="",
        prompt_requested=True,
        aspect_ratio=aspect_ratio,
    )
    await state.set_state(ImageGenerationState.waiting_create_prompt)
    await query.answer()
    is_adult = is_adult_model_key(data.model_key)
    prompt_text = ADULT_CREATE_PROMPT_TEXT if is_adult else CREATE_PROMPT_TEXT
    await edit_or_answer(
        query, text=prompt_text, reply_markup=await ik_create_prompt_nav(is_adult)
    )


@router.message(ImageGenerationState.waiting_create_prompt, F.photo)
@router.message(
    ImageGenerationState.waiting_create_prompt,
    F.document,
    F.document.mime_type.startswith("image/"),
)
async def remind_create_prompt_photo(message: Message, state: FSMContext) -> None:
    data = await get_image_data(state)
    await message.answer(
        "В режиме создания фото не нужны. Пришлите только текстовый промпт.",
        reply_markup=await ik_create_prompt_nav(is_adult_model_key(data.model_key)),
    )


@router.message(StateFilter(None, BaseUserState.main), F.photo)
@router.message(
    StateFilter(None, BaseUserState.main),
    F.document,
    F.document.mime_type.startswith("image/"),
)
async def quick_start_from_photo(
    message: Message,
    state: FSMContext,
) -> None:
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    else:
        return

    data = await get_image_data(state)
    model_key = (
        data.model_key
        if is_image_model_key(data.model_key)
        else DEFAULT_IMAGE_MODEL_KEY
    )

    await update_image_data(
        state,
        model_key=model_key,
        photos=[file_id],
        prompt="",
        prompt_requested=True,
        aspect_ratio="auto",
    )
    await state.set_state(ImageGenerationState.waiting_prompt)
    await message.answer(
        PROMPT_REQUEST_TEXT,
        reply_markup=await ik_prompt_nav(),
    )


@router.message(ImageGenerationState.waiting_create_prompt, F.text)
async def collect_create_prompt(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    await _run_create_generation(
        message=message,
        state=state,
        user=user,
        session=session,
        redis=redis,
        prompt=message.text or "",
    )


@router.message(ImageGenerationState.waiting_create_prompt, F.voice | F.audio)
async def collect_create_prompt_voice(
    message: Message,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    processing_msg = await message.answer("🎙️ Распознаю голосовое сообщение...")

    try:
        prompt = await transcribe_message_audio(message, language="ru")
        if not prompt:
            await processing_msg.edit_text(
                "Не удалось распознать голосовое сообщение. Попробуйте еще раз или введите текстом."
            )
            return

        await processing_msg.delete()
        await message.answer(f"📝 Распознано: {prompt}")
        await _run_create_generation(
            message=message,
            state=state,
            user=user,
            session=session,
            redis=redis,
            prompt=prompt,
        )
    except SpeechRecognitionError as e:
        await processing_msg.edit_text(
            f"❌ Ошибка распознавания: {e}\n\nПопробуйте ввести текстом."
        )
    except Exception:
        await processing_msg.edit_text(
            "❌ Произошла ошибка при обработке голосового сообщения. Попробуйте ввести текстом."
        )


# ─── «✨ Промпт с помощью ИИ» ──────────────────────────────────────────────────
# Кнопка на экране ввода промпта (для генерации и редактирования, кроме 18+):
# дешёвая LLM обогащает черновик или придумывает промпт по теме. См.
# bot/utils/agent_platform.py::generate_image_prompt.


async def _produce_ai_prompt(state: FSMContext) -> tuple[dict, str, str]:
    """Сгенерировать промпт по сохранённым в state параметрам.

    Возвращает (ap, англ. промпт, рус. описание)."""
    data = await state.get_data()
    ap = dict(data.get(AI_PROMPT_STATE_KEY) or {})
    client = build_agent_platform_client()
    prompt, summary = await client.generate_image_prompt(
        text=str(ap.get("input", "")),
        mode=str(ap.get("mode", "enrich")),
        target=str(ap.get("target", "create")),
    )
    ap["generated"] = prompt
    ap["summary"] = summary
    await state.update_data({AI_PROMPT_STATE_KEY: ap})
    return ap, prompt, summary


@router.callback_query(AiPrompt.filter(F.action == "open"))
async def ai_prompt_open(
    query: CallbackQuery,
    callback_data: AiPrompt,
    state: FSMContext,
) -> None:
    target = callback_data.target or "create"
    await state.update_data({AI_PROMPT_STATE_KEY: {"target": target}})
    await query.answer()
    await edit_or_answer(
        query, text=AI_PROMPT_MODE_TEXT, reply_markup=await ik_ai_prompt_modes(target)
    )


@router.callback_query(AiPrompt.filter(F.action.in_({"enrich", "scratch"})))
async def ai_prompt_choose_mode(
    query: CallbackQuery,
    callback_data: AiPrompt,
    state: FSMContext,
) -> None:
    target = callback_data.target or "create"
    mode = callback_data.action
    await state.update_data({AI_PROMPT_STATE_KEY: {"target": target, "mode": mode}})
    await state.set_state(ImageGenerationState.waiting_ai_prompt_input)
    await query.answer()
    text = AI_PROMPT_ENRICH_ASK if mode == "enrich" else AI_PROMPT_SCRATCH_ASK
    await edit_or_answer(
        query, text=text, reply_markup=await ik_ai_prompt_input_back(target)
    )


async def _ai_prompt_from_input(message: Message, state: FSMContext, raw: str) -> None:
    data = await state.get_data()
    ap = dict(data.get(AI_PROMPT_STATE_KEY) or {})
    ap["input"] = raw
    await state.update_data({AI_PROMPT_STATE_KEY: ap})
    wait = await message.answer("✨ Генерирую промпт…")
    try:
        ap2, prompt, summary = await _produce_ai_prompt(state)
    except Exception:
        logger.exception("Не удалось сгенерировать ИИ-промпт")
        await wait.edit_text("❌ Не удалось сгенерировать промпт. Попробуйте ещё раз.")
        return
    await wait.edit_text(
        ai_prompt_result_text(prompt, summary),
        reply_markup=await ik_ai_prompt_result(str(ap2.get("target", "create"))),
    )


@router.message(ImageGenerationState.waiting_ai_prompt_input, F.text)
async def ai_prompt_input_text(message: Message, state: FSMContext) -> None:
    await _ai_prompt_from_input(message, state, message.text or "")


@router.message(ImageGenerationState.waiting_ai_prompt_input, F.voice | F.audio)
async def ai_prompt_input_voice(message: Message, state: FSMContext) -> None:
    processing = await message.answer("🎙️ Распознаю голосовое сообщение...")
    try:
        text = await transcribe_message_audio(message, language="ru")
    except Exception:
        await processing.edit_text("❌ Не удалось распознать. Введите текстом.")
        return
    if not text:
        await processing.edit_text("Не удалось распознать. Введите текстом.")
        return
    await processing.delete()
    await _ai_prompt_from_input(message, state, text)


@router.callback_query(AiPrompt.filter(F.action == "regen"))
async def ai_prompt_regen(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    ap = dict(data.get(AI_PROMPT_STATE_KEY) or {})
    if not ap.get("input"):
        await query.answer("Сначала задайте тему или черновик", show_alert=True)
        return
    await query.answer("Генерирую другой вариант…")
    try:
        ap2, prompt, summary = await _produce_ai_prompt(state)
    except Exception:
        logger.exception("Не удалось перегенерировать ИИ-промпт")
        await query.answer("Ошибка генерации, попробуйте ещё раз", show_alert=True)
        return
    await edit_or_answer(
        query,
        text=ai_prompt_result_text(prompt, summary),
        reply_markup=await ik_ai_prompt_result(str(ap2.get("target", "create"))),
    )


@router.callback_query(AiPrompt.filter(F.action == "accept"))
async def ai_prompt_accept(
    query: CallbackQuery,
    callback_data: AiPrompt,
    state: FSMContext,
    user: UserRD,
    session: AsyncSession,
    redis: Redis,
) -> None:
    data = await state.get_data()
    ap = dict(data.get(AI_PROMPT_STATE_KEY) or {})
    prompt = str(ap.get("generated", "")).strip()
    target = str(ap.get("target") or callback_data.target or "create")
    if not prompt:
        await query.answer("Промпт ещё не готов", show_alert=True)
        return
    await query.answer()
    if not isinstance(query.message, Message):
        return
    if target == "create":
        await state.set_state(ImageGenerationState.waiting_create_prompt)
        await _run_create_generation(
            message=query.message,
            state=state,
            user=user,
            session=session,
            redis=redis,
            prompt=prompt,
        )
    else:
        await state.set_state(ImageGenerationState.waiting_prompt)
        await _run_image_generation(
            message=query.message,
            state=state,
            user=user,
            session=session,
            redis=redis,
            prompt=prompt,
        )


@router.callback_query(AiPrompt.filter(F.action == "back"))
async def ai_prompt_back(
    query: CallbackQuery,
    callback_data: AiPrompt,
    state: FSMContext,
) -> None:
    target = callback_data.target or "create"
    await query.answer()
    if target == "create":
        await state.set_state(ImageGenerationState.waiting_create_prompt)
        await edit_or_answer(
            query,
            text=CREATE_PROMPT_TEXT,
            reply_markup=await ik_create_prompt_nav(False),
        )
    else:
        await state.set_state(ImageGenerationState.waiting_prompt)
        await edit_or_answer(
            query, text=PROMPT_REQUEST_TEXT, reply_markup=await ik_prompt_nav(False)
        )
