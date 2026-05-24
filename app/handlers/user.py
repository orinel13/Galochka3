from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.access import ensure_allowed
from app.config import Settings
from app.db import Database
from app.jobs import JobManager
from app.keyboards import (
    AUDIO_SECTION,
    AUDIO_PHOTO_TO_VIDEO,
    BACK,
    BALANCE,
    GENERATED_AUDIO_TO_VIDEO,
    HELP,
    IMAGE_EDIT,
    IMAGE_SECTION,
    IMAGE_TO_VIDEO,
    MY_JOBS,
    SETTINGS_SECTION,
    TEXT_PHOTO_TO_VIDEO,
    TEXT_TO_AUDIO,
    TEXT_TO_IMAGE,
    VIDEO_SECTION,
    VOICE_MENU,
    VOICE_CURRENT,
    VOICE_LIST,
    VOICE_SELECT,
    VIDEO_DURATION,
    audio_menu,
    choose_voice_keyboard,
    flow_nav_keyboard,
    image_menu,
    job_history_keyboard,
    main_menu,
    options_keyboard,
    prompt_choice_keyboard,
    scenario_keyboard,
    settings_menu,
    user_models_keyboard,
    video_menu,
    voice_menu,
    voices_keyboard,
)
from app.models import JobType
from app.navigation import BACK_TEXTS, MENU_TEXTS, clear_stack, pop_screen, push_screen
from app.services.credits_service import CreditsService
from app.services.model_service import ModelService
from app.states import AudioPhotoVideoState, GeneratedAudioVideoState, ImageEditState, ImageToVideoState, TextPhotoVideoState, TextToAudioState, TextToImageState
from app.ui_messages import delete_tracked_messages, track_ui_message
from app.utils import now_iso, short_error

router = Router()


async def send_ui(message: Message, text: str, **kwargs):
    sent = await message.answer(text, **kwargs)
    track_ui_message(sent.chat.id, sent.message_id)
    return sent


async def cleanup_ui(message: Message, state: FSMContext | None = None, delete_trigger: bool = True) -> None:
    if state is not None:
        await state.clear()
    await delete_tracked_messages(message.bot, message.chat.id)
    if delete_trigger:
        try:
            await message.delete()
        except Exception:
            pass


def is_admin_user(settings: Settings, telegram_id: int) -> bool:
    return telegram_id == settings.admin_telegram_id


@router.message(Command("help"))
@router.message(F.text == HELP)
async def help_message(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await send_ui(
        message,
        "Доступные действия:\n"
        "🎙 Аудио\n"
        "🎬 Видео\n"
        "🖼 Изображения\n"
        "🎭 Голос\n"
        "⚙️ Настройки\n"
        "📊 Баланс\n"
        "🕘 Мои задачи",
        reply_markup=main_menu(),
    )


@router.message(F.text.in_(MENU_TEXTS))
async def go_main_menu(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await clear_stack(db, message.from_user.id)
    await send_ui(message, "Главное меню", reply_markup=main_menu())


@router.message(F.text.in_(BACK_TEXTS))
async def universal_back(message: Message, state: FSMContext, db: Database, settings: Settings, models: ModelService) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    previous = await pop_screen(db, message.from_user.id)
    await render_user_screen(message, db, settings, models, previous)


@router.callback_query(lambda c: c.data in {"nav_back", "nav_menu"})
async def universal_nav_callback(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings, models: ModelService) -> None:
    row = await db.get_user(callback.from_user.id)
    if callback.from_user.id != settings.admin_telegram_id and not (row and row["is_allowed"]):
        await callback.answer("Доступ не выдан.", show_alert=True)
        return
    await cleanup_ui(callback.message, state, delete_trigger=False)
    if callback.data == "nav_menu":
        await clear_stack(db, callback.from_user.id)
        await send_ui(callback.message, "Главное меню", reply_markup=main_menu())
    else:
        previous = await pop_screen(db, callback.from_user.id)
        await render_user_screen(callback.message, db, settings, models, previous, user_id=callback.from_user.id)
    await callback.answer()


@router.message(F.text == AUDIO_SECTION)
async def open_audio_menu(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await clear_stack(db, message.from_user.id)
    await push_screen(db, message.from_user.id, "main")
    await send_ui(message, "Аудио-сценарии", reply_markup=audio_menu())


@router.message(F.text == VIDEO_SECTION)
async def open_video_menu(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await clear_stack(db, message.from_user.id)
    await push_screen(db, message.from_user.id, "main")
    await send_ui(message, "Видео-сценарии", reply_markup=video_menu(is_admin_user(settings, message.from_user.id)))


@router.message(F.text == IMAGE_SECTION)
async def open_image_menu(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await clear_stack(db, message.from_user.id)
    await push_screen(db, message.from_user.id, "main")
    await send_ui(message, "Изображения", reply_markup=image_menu(is_admin_user(settings, message.from_user.id)))


@router.message(F.text == VOICE_MENU)
async def open_voice_menu(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await clear_stack(db, message.from_user.id)
    await push_screen(db, message.from_user.id, "main")
    await send_ui(message, "Голос", reply_markup=voice_menu())


@router.message(F.text == SETTINGS_SECTION)
async def open_settings_menu(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await clear_stack(db, message.from_user.id)
    await push_screen(db, message.from_user.id, "main")
    await send_ui(message, "Настройки", reply_markup=settings_menu())


@router.message(F.text == BACK)
async def back_to_main(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await clear_stack(db, message.from_user.id)
    await send_ui(message, "Главное меню", reply_markup=main_menu())


@router.message(F.text.in_({TEXT_PHOTO_TO_VIDEO, AUDIO_PHOTO_TO_VIDEO, IMAGE_TO_VIDEO, TEXT_TO_IMAGE, IMAGE_EDIT}))
async def scenario_entry(message: Message, state: FSMContext, db: Database, settings: Settings, models: ModelService) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    scenario = {
        TEXT_PHOTO_TO_VIDEO: "video_from_text",
        AUDIO_PHOTO_TO_VIDEO: "video_from_uploaded_audio",
        IMAGE_TO_VIDEO: "image_to_video",
        TEXT_TO_IMAGE: "text_to_image",
        IMAGE_EDIT: "image_edit",
    }[message.text]
    section = "image_menu" if scenario in {"text_to_image", "image_edit"} else "video_menu"
    await push_screen(db, message.from_user.id, section)
    await show_scenario_card(message, db, settings, models, scenario)


async def render_user_screen(
    message: Message,
    db: Database,
    settings: Settings,
    models: ModelService,
    screen: dict | None,
    user_id: int | None = None,
) -> None:
    tg_id = user_id or message.from_user.id
    screen_name = (screen or {}).get("screen") if screen else "main"
    payload = (screen or {}).get("payload") or {}
    if screen_name == "audio_menu":
        await send_ui(message, "Аудио-сценарии", reply_markup=audio_menu())
    elif screen_name == "video_menu":
        await send_ui(message, "Видео-сценарии", reply_markup=video_menu(is_admin_user(settings, tg_id)))
    elif screen_name == "image_menu":
        await send_ui(message, "Изображения", reply_markup=image_menu(is_admin_user(settings, tg_id)))
    elif screen_name == "voice_menu":
        await send_ui(message, "Голос", reply_markup=voice_menu())
    elif screen_name == "settings_menu":
        await send_ui(message, "Настройки", reply_markup=settings_menu())
    elif screen_name == "scenario":
        scenario = payload.get("scenario")
        if scenario:
            await show_scenario_card(message, db, settings, models, scenario, user_id=tg_id)
        else:
            await send_ui(message, "Главное меню", reply_markup=main_menu())
    else:
        await send_ui(message, "Главное меню", reply_markup=main_menu())


async def show_scenario_card(message: Message, db: Database, settings: Settings, models: ModelService, scenario: str, user_id: int | None = None) -> None:
    tg_id = user_id or message.from_user.id
    user_settings = await db.get_user_settings(tg_id)
    voice = await selected_or_default_voice(db, tg_id)
    family = "image" if scenario in {"text_to_image", "image_edit"} else ("video" if scenario == "image_to_video" else "avatar")
    selected_model = await models.selected_model_for_user(tg_id, family)
    if not selected_model:
        compatible = await compatible_models_for_family(models, family, user_settings)
        selected_model = compatible[0] if compatible else None
    prompt = await default_prompt_for_scenario(settings, db, scenario)
    title = {
        "video_from_text": "Текст + фото → avatar video",
        "video_from_uploaded_audio": "Аудио + фото → avatar video",
        "image_to_video": "Фото → видео без аудио",
        "text_to_image": "Текст → изображение",
        "image_edit": "Редактировать изображение",
    }[scenario]
    lines = [f"Сценарий: {title}"]
    if scenario == "video_from_text":
        lines.append(f"Голос: {(voice or {}).get('name') or 'не выбран'}")
    elif scenario == "video_from_generated_audio":
        lines.append("Source audio job: выбери из истории аудио")
    model_label = "Image" if family == "image" else ("Video" if family == "video" else "Avatar")
    lines.append(f"{model_label} model: {(selected_model or {}).get('name') or 'не выбрана'}")
    lines.append(f"Aspect ratio: {user_settings['image_aspect_ratio'] if family == 'image' else user_settings['video_aspect_ratio']}")
    lines.append(f"Resolution: {user_settings['image_resolution'] if family == 'image' else user_settings['video_resolution']}")
    if family in {"video", "avatar"}:
        lines.append(f"Duration: {user_settings['video_duration_ms']} ms")
    lines.append(f"Prompt: {'по умолчанию' if prompt else 'не задан'}")
    text = "\n".join(lines)
    include_voice = scenario in {"video_from_text", "video_from_uploaded_audio"}
    await send_ui(
        message,
        text,
        reply_markup=scenario_keyboard(
            scenario,
            include_voice=include_voice,
            include_model=is_admin_user(settings, tg_id),
            include_prompt=scenario != "text_to_image",
        ),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("scenario_continue:"))
async def scenario_continue(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings, models: ModelService) -> None:
    row = await db.get_user(callback.from_user.id)
    if callback.from_user.id != settings.admin_telegram_id and not (row and row["is_allowed"]):
        await callback.answer("Доступ не выдан.", show_alert=True)
        return
    scenario = callback.data.split(":", 1)[1]
    if scenario in {"video_from_text", "video_from_uploaded_audio"} and not await selected_or_default_voice(db, callback.from_user.id):
        await send_ui(callback.message, "Сначала выбери голос.", reply_markup=choose_voice_keyboard())
        await callback.answer()
        return
    await cleanup_ui(callback.message, delete_trigger=False)
    await push_screen(db, callback.from_user.id, "scenario", {"scenario": scenario})
    if scenario == "video_from_text":
        await state.set_state(TextPhotoVideoState.waiting_photo)
        await state.update_data(prompt_mode="default", text_prompt=settings.default_avatar_prompt)
        await send_ui(callback.message, "Пришли фото для avatar video.", reply_markup=flow_nav_keyboard())
    elif scenario == "video_from_uploaded_audio":
        await state.set_state(AudioPhotoVideoState.waiting_photo)
        await state.update_data(prompt_mode="default", text_prompt=settings.default_avatar_prompt)
        await send_ui(callback.message, "Пришли фото для avatar video.", reply_markup=flow_nav_keyboard())
    elif scenario == "image_to_video":
        await state.set_state(ImageToVideoState.waiting_photo)
        await send_ui(callback.message, "Пришли фото для видео без аудио.", reply_markup=flow_nav_keyboard())
    elif scenario == "text_to_image":
        await state.set_state(TextToImageState.waiting_prompt)
        await send_ui(callback.message, "Опиши изображение, которое нужно сгенерировать.", reply_markup=flow_nav_keyboard())
    elif scenario == "image_edit":
        await state.set_state(ImageEditState.waiting_image)
        await send_ui(callback.message, "Пришли изображение для редактирования.", reply_markup=flow_nav_keyboard())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("scenario_prompt:"))
async def scenario_prompt(callback: CallbackQuery) -> None:
    scenario = callback.data.split(":", 1)[1]
    await send_ui(callback.message, "Хочешь добавить текстовое описание движения/сцены?", reply_markup=prompt_choice_keyboard(scenario))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("scenario_model:"))
async def scenario_model(callback: CallbackQuery, db: Database, settings: Settings, models: ModelService) -> None:
    if callback.from_user.id != settings.admin_telegram_id:
        await callback.answer("Модель выбирает администратор.", show_alert=True)
        return
    family = "image" if callback.data.endswith(("text_to_image", "image_edit")) else ("video" if callback.data.endswith("image_to_video") else "avatar")
    await show_model_picker(callback.message, db, settings, models, callback.from_user.id, family)
    await callback.answer()


@router.callback_query(lambda c: c.data in {"setting:video_duration_ms", "setting:video_quality"})
async def scenario_setting(callback: CallbackQuery) -> None:
    if callback.data == "setting:video_duration_ms":
        await send_ui(
            callback.message,
            "Выбери длительность видео:",
            reply_markup=options_keyboard("video_duration_ms", ["5000", "6000", "7000", "8000", "9000", "10000", "11000", "12000", "13000", "14000", "15000"]),
        )
    else:
        await send_ui(callback.message, "Качество меняется в разделе ⚙️ Настройки: Video aspect ratio / Video resolution.")
    await callback.answer()


@router.callback_query(lambda c: c.data == "scenario_back")
async def scenario_back(callback: CallbackQuery, db: Database, settings: Settings, models: ModelService) -> None:
    await cleanup_ui(callback.message, delete_trigger=False)
    previous = await pop_screen(db, callback.from_user.id)
    await render_user_screen(callback.message, db, settings, models, previous, user_id=callback.from_user.id)
    await callback.answer()


@router.message(Command("voices"))
@router.message(Command("setvoice"))
@router.message(Command("balance"))
@router.message(F.text.in_({VOICE_SELECT, VOICE_LIST, VOICE_CURRENT, BALANCE, MY_JOBS, "История аудио", GENERATED_AUDIO_TO_VIDEO}))
async def priority_utility_buttons(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    credits: CreditsService,
) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    command = (message.text or "").split(maxsplit=1)[0].lower()
    if message.text == VOICE_SELECT or command == "/setvoice":
        rows = await db.fetchall("SELECT name, hedra_voice_id FROM voices WHERE is_active=1 ORDER BY is_default DESC, name")
        if not rows:
            await send_ui(message, "Активных голосов пока нет.")
        else:
            await send_ui(message, "Выбери голос:", reply_markup=voices_keyboard([dict(row) for row in rows]))
    elif message.text == VOICE_LIST or command == "/voices":
        rows = await db.fetchall("SELECT name, hedra_voice_id FROM voices WHERE is_active=1 ORDER BY is_default DESC, name")
        if not rows:
            await send_ui(message, "Активных голосов пока нет. Попроси администратора добавить voice_id.")
        else:
            text = "Активные голоса:\n" + "\n".join(f"• {row['name']}" for row in rows)
            await send_ui(message, text, reply_markup=voices_keyboard([dict(row) for row in rows]))
    elif message.text == VOICE_CURRENT:
        voice = await selected_or_default_voice(db, message.from_user.id)
        await send_ui(message, f"Текущий голос: {voice['name']}" if voice else "Голос не выбран.", reply_markup=choose_voice_keyboard())
    elif message.text == BALANCE or command == "/balance":
        try:
            data = await credits.get_credits(save_snapshot=False)
            remaining = credits.remaining(data)
            await send_ui(message, f"Hedra credits: {remaining if remaining is not None else 'не удалось определить'}")
        except Exception as exc:
            await send_ui(message, f"Не удалось получить баланс: {short_error(str(exc))}")
    elif message.text in {"История аудио", GENERATED_AUDIO_TO_VIDEO}:
        await send_audio_history(message, db)
    else:
        await send_jobs_history(message, db)


@router.message(F.text.in_({"Текущие параметры", "Video aspect ratio", "Video resolution", VIDEO_DURATION, "Image aspect ratio", "Image resolution", "TTS speed", "TTS stability", "Очистить временные результаты", "Prompt для видео", "Prompt для изображения"}))
async def priority_settings_buttons(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager, models: ModelService) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    if message.text == "Текущие параметры":
        user_settings = await db.get_user_settings(message.from_user.id)
        voice = await selected_or_default_voice(db, message.from_user.id)
        avatar = await models.selected_model_for_user(message.from_user.id, "avatar")
        video = await models.selected_model_for_user(message.from_user.id, "video")
        image = await models.selected_model_for_user(message.from_user.id, "image")
        await send_ui(
            message,
            "Текущие параметры\n"
            f"Голос: {(voice or {}).get('name') or 'не выбран'}\n"
            f"Avatar model: {(avatar or {}).get('name') or 'по умолчанию'}\n"
            f"Video model: {(video or {}).get('name') or 'по умолчанию'}\n"
            f"Image model: {(image or {}).get('name') or 'по умолчанию'}\n"
            f"Video: {user_settings['video_aspect_ratio']} / {user_settings['video_resolution']} / {user_settings['video_duration_ms']} ms\n"
            f"Image: {user_settings['image_aspect_ratio']} / {user_settings['image_resolution']}\n"
            f"TTS: speed={user_settings['tts_speed']} stability={user_settings['tts_stability']}",
        )
        return
    if message.text == "Prompt для видео":
        await send_ui(message, "Prompt задаётся внутри выбранного видео-сценария перед постановкой задачи.", reply_markup=video_menu(is_admin_user(settings, message.from_user.id)))
        return
    if message.text == "Prompt для изображения":
        await send_ui(message, "Prompt задаётся внутри сценария изображения перед постановкой задачи.", reply_markup=image_menu(is_admin_user(settings, message.from_user.id)))
        return
    if message.text == "Очистить временные результаты":
        rows = await db.fetchall("SELECT id FROM jobs WHERE telegram_id=? AND local_result_path IS NOT NULL", (message.from_user.id,))
        removed = 0
        for row in rows:
            if await jobs.delete_local_result(row["id"], message.from_user.id, False):
                removed += 1
        await send_ui(message, f"Локальные временные результаты удалены: {removed}")
        return
    options = {
        "Video aspect ratio": ("video_aspect_ratio", ["1:1", "9:16", "16:9"]),
        "Video resolution": ("video_resolution", ["540p", "720p", "1080p"]),
        VIDEO_DURATION: ("video_duration_ms", ["5000", "6000", "7000", "8000", "9000", "10000", "11000", "12000", "13000", "14000", "15000"]),
        "Image aspect ratio": ("image_aspect_ratio", ["1:1", "9:16", "16:9"]),
        "Image resolution": ("image_resolution", ["540p", "720p", "1080p"]),
        "TTS speed": ("tts_speed", ["0.7", "0.85", "1.0", "1.1", "1.2"]),
        "TTS stability": ("tts_stability", ["0.0", "0.25", "0.5", "0.75", "1.0"]),
    }[message.text]
    await send_ui(message, f"Выбери значение: {message.text}", reply_markup=options_keyboard(options[0], options[1]))


@router.message(F.text == TEXT_TO_AUDIO)
async def text_to_audio_start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await push_screen(db, message.from_user.id, "audio_menu")
    await state.set_state(TextToAudioState.waiting_text)
    await send_ui(message, "Отправь текст для озвучки.", reply_markup=flow_nav_keyboard())


@router.message(TextToAudioState.waiting_text)
async def text_to_audio_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    text = (message.text or "").strip()
    if not text:
        await send_ui(message, "Пришли текст сообщением.")
        return
    if len(text) > settings.max_text_chars_tts:
        await send_ui(message, f"Текст слишком длинный. Лимит: {settings.max_text_chars_tts} символов.")
        return
    voice = await selected_or_default_voice(db, message.from_user.id)
    if not voice:
        await send_ui(
            message,
            "Голос не выбран. Выбери голос из списка.",
            reply_markup=choose_voice_keyboard(),
        )
        return
    job_id = await jobs.create_job(
        telegram_id=message.from_user.id,
        job_type=JobType.TTS.value,
        text=text,
        voice_id=voice["hedra_voice_id"],
        voice_name=voice["name"],
    )
    await state.clear()
    await send_ui(message, f"Задача #{job_id} поставлена в очередь.")


@router.message(F.text == TEXT_PHOTO_TO_VIDEO)
async def text_photo_video_start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await push_screen(db, message.from_user.id, "scenario", {"scenario": "video_from_text"})
    await state.set_state(TextPhotoVideoState.waiting_photo)
    await send_ui(message, "Пришли фото для видео.", reply_markup=flow_nav_keyboard())


@router.message(TextPhotoVideoState.waiting_photo)
async def text_photo_video_photo(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await send_ui(message, "Пришли фото JPG или PNG.")
        return
    await state.update_data(image_file_id=file_id)
    await state.set_state(TextPhotoVideoState.waiting_text)
    await send_ui(message, "Теперь отправь текст для видео.", reply_markup=flow_nav_keyboard())


@router.message(TextPhotoVideoState.waiting_text)
async def text_photo_video_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    text = (message.text or "").strip()
    if not text:
        await send_ui(message, "Пришли текст сообщением.")
        return
    if len(text) > settings.max_text_chars_video:
        await send_ui(message, f"Текст слишком длинный. Лимит: {settings.max_text_chars_video} символов.")
        return
    voice = await selected_or_default_voice(db, message.from_user.id)
    if not voice:
        await send_ui(
            message,
            "Голос не выбран. Выбери голос из списка.",
            reply_markup=choose_voice_keyboard(),
        )
        return
    await state.update_data(text=text, voice_id=voice["hedra_voice_id"], voice_name=voice["name"])
    await state.set_state(TextPhotoVideoState.waiting_prompt_choice)
    await send_ui(message, "Хочешь добавить текстовое описание движения/сцены?", reply_markup=prompt_choice_keyboard("video_from_text"))


@router.message(F.text == AUDIO_PHOTO_TO_VIDEO)
async def audio_photo_video_start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await cleanup_ui(message, state)
    await push_screen(db, message.from_user.id, "scenario", {"scenario": "video_from_uploaded_audio"})
    await state.set_state(AudioPhotoVideoState.waiting_photo)
    await send_ui(message, "Пришли фото для видео.", reply_markup=flow_nav_keyboard())


@router.message(AudioPhotoVideoState.waiting_photo)
async def audio_photo_video_photo(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await send_ui(message, "Пришли фото JPG или PNG.")
        return
    await state.update_data(image_file_id=file_id)
    await state.set_state(AudioPhotoVideoState.waiting_audio)
    await send_ui(message, "Теперь пришли аудио, voice или audio-документ mp3/wav/ogg.", reply_markup=flow_nav_keyboard())


@router.message(AudioPhotoVideoState.waiting_audio)
async def audio_photo_video_audio(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    audio_file_id = get_audio_file_id(message)
    if not audio_file_id:
        await send_ui(message, "Пришли аудио, voice или audio-документ mp3/wav/ogg.")
        return
    await state.update_data(audio_file_id=audio_file_id)
    await state.set_state(AudioPhotoVideoState.waiting_prompt_choice)
    await send_ui(message, "Хочешь добавить текстовое описание движения/сцены?", reply_markup=prompt_choice_keyboard("video_from_uploaded_audio"))


@router.callback_query(lambda c: c.data and c.data.startswith("audio_to_video:"))
async def audio_to_video(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.from_user:
        await callback.answer("Не удалось определить пользователя.", show_alert=True)
        return
    row = await db.get_user(callback.from_user.id)
    is_admin = callback.from_user.id == settings.admin_telegram_id
    if not is_admin and not (row and row["is_allowed"]):
        await callback.answer("Доступ не выдан.", show_alert=True)
        return
    job_id = int(callback.data.split(":", 1)[1])
    job = await db.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job or (not is_admin and job["telegram_id"] != callback.from_user.id):
        await callback.answer("Задача недоступна.", show_alert=True)
        return
    if job["status"] != "complete":
        await callback.answer("Аудио ещё не готово.", show_alert=True)
        return
    if not (job["local_result_path"] and Path(job["local_result_path"]).exists()) and not (
        job["result_download_url"] or job["result_streaming_url"]
    ):
        await send_ui(callback.message, "Аудиофайл уже очищен. Сгенерируй аудио заново.")
        await callback.answer()
        return
    await cleanup_ui(callback.message, state, delete_trigger=False)
    await push_screen(db, callback.from_user.id, "scenario", {"scenario": "video_from_generated_audio"})
    await state.set_state(GeneratedAudioVideoState.waiting_photo)
    await state.update_data(source_audio_job_id=job_id)
    await send_ui(callback.message, "Пришли фото для видео из этого аудио.", reply_markup=flow_nav_keyboard())
    await callback.answer()


@router.message(GeneratedAudioVideoState.waiting_photo)
async def generated_audio_video_photo(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await send_ui(message, "Пришли фото JPG или PNG.")
        return
    data = await state.get_data()
    source_job_id = int(data["source_audio_job_id"])
    await state.update_data(source_image_file_id=file_id)
    await state.set_state(GeneratedAudioVideoState.waiting_prompt_choice)
    await send_ui(message, "Хочешь добавить текстовое описание движения/сцены?", reply_markup=prompt_choice_keyboard("video_from_generated_audio"))


async def create_generated_audio_video_job(message: Message, state: FSMContext, db: Database, jobs: JobManager, text_prompt: str | None, prompt_mode: str) -> None:
    data = await state.get_data()
    source_job_id = int(data["source_audio_job_id"])
    source = await db.fetchone("SELECT * FROM jobs WHERE id=?", (source_job_id,))
    telegram_id = message.chat.id
    model = await selected_model_for_job(db, telegram_id, "avatar")
    job_id = await jobs.create_job(
        telegram_id=telegram_id,
        job_type=JobType.VIDEO_FROM_GENERATED_AUDIO.value,
        generation_family="avatar_video",
        parent_job_id=source_job_id,
        source_audio_job_id=source_job_id,
        voice_id=source["voice_id"] if source else None,
        voice_name=source["voice_name"] if source else None,
        source_image_file_id=data["source_image_file_id"],
        text_prompt=text_prompt,
        prompt_mode=prompt_mode,
        selected_model_id=model["id"] if model else None,
        selected_model_name=model["name"] if model else None,
    )
    await state.clear()
    await send_ui(message, f"Задача #{job_id} поставлена в очередь.")


async def create_text_photo_video_job(message: Message, state: FSMContext, db: Database, jobs: JobManager, text_prompt: str | None, prompt_mode: str) -> None:
    data = await state.get_data()
    telegram_id = message.chat.id
    model = await selected_model_for_job(db, telegram_id, "avatar")
    job_id = await jobs.create_job(
        telegram_id=telegram_id,
        job_type=JobType.VIDEO_FROM_TEXT.value,
        generation_family="avatar_video",
        text=data["text"],
        voice_id=data["voice_id"],
        voice_name=data["voice_name"],
        image_file_id=data["image_file_id"],
        text_prompt=text_prompt,
        prompt_mode=prompt_mode,
        selected_model_id=model["id"] if model else None,
        selected_model_name=model["name"] if model else None,
    )
    await state.clear()
    await send_ui(message, f"Задача #{job_id} поставлена в очередь.")


async def create_uploaded_audio_video_job(message: Message, state: FSMContext, db: Database, jobs: JobManager, text_prompt: str | None, prompt_mode: str) -> None:
    data = await state.get_data()
    telegram_id = message.chat.id
    model = await selected_model_for_job(db, telegram_id, "avatar")
    job_id = await jobs.create_job(
        telegram_id=telegram_id,
        job_type=JobType.VIDEO_FROM_UPLOADED_AUDIO.value,
        generation_family="avatar_video",
        image_file_id=data["image_file_id"],
        audio_file_id=data["audio_file_id"],
        text_prompt=text_prompt,
        prompt_mode=prompt_mode,
        selected_model_id=model["id"] if model else None,
        selected_model_name=model["name"] if model else None,
    )
    await state.clear()
    await send_ui(message, f"Задача #{job_id} поставлена в очередь.")


async def create_image_to_video_job(message: Message, state: FSMContext, db: Database, jobs: JobManager, text_prompt: str | None, prompt_mode: str) -> None:
    data = await state.get_data()
    telegram_id = message.chat.id
    user_settings = await db.get_user_settings(telegram_id)
    model = await selected_model_for_job(db, telegram_id, "video")
    job_id = await jobs.create_job(
        telegram_id=telegram_id,
        job_type=JobType.IMAGE_TO_VIDEO.value,
        generation_family="image_to_video",
        image_file_id=data["image_file_id"],
        text_prompt=text_prompt,
        prompt_mode=prompt_mode,
        duration_ms=user_settings["video_duration_ms"],
        selected_model_id=model["id"] if model else None,
        selected_model_name=model["name"] if model else None,
    )
    await state.clear()
    await send_ui(message, f"Задача #{job_id} поставлена в очередь.")


@router.callback_query(lambda c: c.data and c.data.startswith(("prompt_skip:", "prompt_default:")))
async def prompt_quick_choice(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    row = await db.get_user(callback.from_user.id)
    if callback.from_user.id != settings.admin_telegram_id and not (row and row["is_allowed"]):
        await callback.answer("Доступ не выдан.", show_alert=True)
        return
    action, scenario = callback.data.split(":", 1)
    current = await state.get_state()
    prompt: str | None = None
    mode = "skip"
    if action == "prompt_default":
        mode = "default"
        prompt = settings.default_video_no_audio_prompt if scenario == "image_to_video" else settings.default_avatar_prompt
    if current == TextPhotoVideoState.waiting_prompt_choice.state:
        await create_text_photo_video_job(callback.message, state, db, jobs, prompt, mode)
    elif current == AudioPhotoVideoState.waiting_prompt_choice.state:
        await create_uploaded_audio_video_job(callback.message, state, db, jobs, prompt, mode)
    elif current == GeneratedAudioVideoState.waiting_prompt_choice.state:
        await create_generated_audio_video_job(callback.message, state, db, jobs, prompt, mode)
    elif current == ImageToVideoState.waiting_prompt_choice.state:
        await create_image_to_video_job(callback.message, state, db, jobs, prompt, mode)
    else:
        await send_ui(callback.message, "Сначала выбери сценарий и входные файлы.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("prompt_write:"))
async def prompt_write(callback: CallbackQuery, state: FSMContext) -> None:
    scenario = callback.data.split(":", 1)[1]
    current = await state.get_state()
    if current == TextPhotoVideoState.waiting_prompt_choice.state:
        await state.set_state(TextPhotoVideoState.waiting_prompt_text)
    elif current == AudioPhotoVideoState.waiting_prompt_choice.state:
        await state.set_state(AudioPhotoVideoState.waiting_prompt_text)
    elif current == GeneratedAudioVideoState.waiting_prompt_choice.state:
        await state.set_state(GeneratedAudioVideoState.waiting_prompt_text)
    elif current == ImageToVideoState.waiting_prompt_choice.state:
        await state.set_state(ImageToVideoState.waiting_prompt_text)
    else:
        await send_ui(callback.message, "Сначала выбери сценарий и входные файлы.")
        await callback.answer()
        return
    await send_ui(callback.message, "Напиши prompt одним сообщением.", reply_markup=flow_nav_keyboard())
    await callback.answer()


@router.message(TextPhotoVideoState.waiting_prompt_text)
async def text_photo_video_prompt_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await create_text_photo_video_job(message, state, db, jobs, (message.text or "").strip(), "custom")


@router.message(AudioPhotoVideoState.waiting_prompt_text)
async def uploaded_audio_video_prompt_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await create_uploaded_audio_video_job(message, state, db, jobs, (message.text or "").strip(), "custom")


@router.message(GeneratedAudioVideoState.waiting_prompt_text)
async def generated_audio_video_prompt_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await create_generated_audio_video_job(message, state, db, jobs, (message.text or "").strip(), "custom")


@router.message(ImageToVideoState.waiting_photo)
async def image_to_video_photo(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await send_ui(message, "Пришли фото JPG или PNG.")
        return
    await state.update_data(image_file_id=file_id)
    await state.set_state(ImageToVideoState.waiting_prompt_choice)
    await send_ui(message, "Хочешь добавить текстовое описание движения/сцены?", reply_markup=prompt_choice_keyboard("image_to_video"))


@router.message(ImageToVideoState.waiting_prompt_text)
async def image_to_video_prompt_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await create_image_to_video_job(message, state, db, jobs, (message.text or "").strip(), "custom")


@router.message(TextToImageState.waiting_prompt)
async def text_to_image_prompt(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    prompt = (message.text or "").strip()
    if not prompt:
        await send_ui(message, "Prompt не должен быть пустым.")
        return
    model = await selected_model_for_job(db, message.from_user.id, "image")
    job_id = await jobs.create_job(
        telegram_id=message.from_user.id,
        job_type=JobType.TEXT_TO_IMAGE.value,
        generation_family="image_generation",
        text_prompt=prompt,
        prompt_mode="custom",
        selected_model_id=model["id"] if model else None,
        selected_model_name=model["name"] if model else None,
    )
    await state.clear()
    await send_ui(message, f"Задача #{job_id} поставлена в очередь.")


@router.message(ImageEditState.waiting_image)
async def image_edit_image(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await send_ui(message, "Пришли фото JPG или PNG.")
        return
    await state.update_data(image_file_id=file_id)
    await state.set_state(ImageEditState.waiting_prompt)
    await send_ui(
        message,
        "Напиши prompt редактирования.\n"
        "Например: замени фон на студийный, сделай тёплый вечерний свет, сохрани лицо и позу.",
        reply_markup=flow_nav_keyboard(),
    )


@router.message(ImageEditState.waiting_prompt)
async def image_edit_prompt(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    prompt = (message.text or "").strip()
    if not prompt:
        await send_ui(message, "Prompt не должен быть пустым.")
        return
    data = await state.get_data()
    model = await selected_model_for_job(db, message.from_user.id, "image")
    job_id = await jobs.create_job(
        telegram_id=message.from_user.id,
        job_type=JobType.IMAGE_EDIT.value,
        generation_family="image_edit",
        image_file_id=data["image_file_id"],
        text_prompt=prompt,
        prompt_mode="custom",
        selected_model_id=model["id"] if model else None,
        selected_model_name=model["name"] if model else None,
    )
    await state.clear()
    await send_ui(message, f"Задача #{job_id} поставлена в очередь.")


@router.callback_query(lambda c: c.data and c.data.startswith("repeat_audio:"))
async def repeat_audio(callback: CallbackQuery, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not callback.from_user:
        return
    admin = callback.from_user.id == settings.admin_telegram_id
    source_job_id = int(callback.data.split(":", 1)[1])
    source = await db.fetchone("SELECT * FROM jobs WHERE id=?", (source_job_id,))
    if not source or (not admin and source["telegram_id"] != callback.from_user.id):
        await callback.answer("Задача недоступна.", show_alert=True)
        return
    job_id = await jobs.repeat_audio(source_job_id, callback.from_user.id)
    if not job_id:
        await callback.answer("Не удалось повторить задачу.", show_alert=True)
        return
    await send_ui(callback.message, f"Задача #{job_id} поставлена в очередь.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("delete_result:"))
async def delete_result(callback: CallbackQuery, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not callback.from_user:
        return
    admin = callback.from_user.id == settings.admin_telegram_id
    job_id = int(callback.data.split(":", 1)[1])
    ok = await jobs.delete_local_result(job_id, callback.from_user.id, admin)
    await send_ui(callback.message, "Локальный файл результата удалён." if ok else "Задача недоступна.")
    await callback.answer()


@router.message(Command("voices"))
@router.message(F.text == VOICE_LIST)
async def voices(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    rows = await db.fetchall("SELECT name, hedra_voice_id FROM voices WHERE is_active=1 ORDER BY is_default DESC, name")
    if not rows:
        await send_ui(message, "Активных голосов пока нет. Попроси администратора добавить voice_id.")
        return
    text = "Активные голоса:\n" + "\n".join(f"• {row['name']}" for row in rows)
    await send_ui(message, text, reply_markup=voices_keyboard([dict(row) for row in rows]))


@router.message(Command("setvoice"))
@router.message(F.text == VOICE_SELECT)
@router.callback_query(lambda c: c.data == "open_setvoice")
async def setvoice(event: Message | CallbackQuery, db: Database, settings: Settings) -> None:
    message = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, Message) and not await ensure_allowed(event, db, settings):
        return
    if isinstance(event, CallbackQuery):
        row = await db.get_user(event.from_user.id)
        if event.from_user.id != settings.admin_telegram_id and not (row and row["is_allowed"]):
            await event.answer("Доступ не выдан.", show_alert=True)
            return
    rows = await db.fetchall("SELECT name, hedra_voice_id FROM voices WHERE is_active=1 ORDER BY is_default DESC, name")
    if not rows:
        await send_ui(message, "Активных голосов пока нет.")
    else:
        await send_ui(message, "Выбери голос:", reply_markup=voices_keyboard([dict(row) for row in rows]))
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(F.text == VOICE_CURRENT)
async def current_voice(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    voice = await selected_or_default_voice(db, message.from_user.id)
    await send_ui(message, f"Текущий голос: {voice['name']}" if voice else "Голос не выбран.", reply_markup=choose_voice_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("setvoice:"))
async def setvoice_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    user = callback.from_user
    row_user = await db.get_user(user.id)
    if user.id != settings.admin_telegram_id and not (row_user and row_user["is_allowed"]):
        await callback.answer("Доступ не выдан.", show_alert=True)
        return
    voice_id = callback.data.split(":", 1)[1]
    row = await db.fetchone("SELECT * FROM voices WHERE hedra_voice_id=? AND is_active=1", (voice_id,))
    if not row:
        await callback.answer("Голос недоступен.", show_alert=True)
        return
    await db.execute(
        "UPDATE users SET selected_voice_id=?, selected_voice_name=?, updated_at=? WHERE telegram_id=?",
        (row["hedra_voice_id"], row["name"], now_iso(), callback.from_user.id),
    )
    await send_ui(callback.message, f"Выбран голос: {row['name']}")
    await callback.answer()


@router.message(Command("balance"))
@router.message(F.text == BALANCE)
async def balance(message: Message, db: Database, settings: Settings, credits: CreditsService) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    try:
        data = await credits.get_credits(save_snapshot=False)
        remaining = credits.remaining(data)
        await send_ui(message, f"Hedra credits: {remaining if remaining is not None else 'не удалось определить'}")
    except Exception as exc:
        await send_ui(message, f"Не удалось получить баланс: {short_error(str(exc))}")


@router.message(F.text == MY_JOBS)
async def my_jobs(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await send_jobs_history(message, db)


@router.message(F.text.in_({"История аудио", GENERATED_AUDIO_TO_VIDEO}))
async def audio_history(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await send_audio_history(message, db)


async def send_jobs_history(message: Message, db: Database) -> None:
    rows = await db.fetchall(
        "SELECT * FROM jobs WHERE telegram_id=? ORDER BY id DESC LIMIT 10",
        (message.from_user.id,),
    )
    if not rows:
        await send_ui(message, "Задач пока нет.")
        return
    for row in rows:
        text = format_job(dict(row))
        await send_ui(message, text, reply_markup=job_history_keyboard(row["id"], row["job_type"], bool(row["local_result_path"])))


async def send_audio_history(message: Message, db: Database) -> None:
    rows = await db.fetchall(
        "SELECT * FROM jobs WHERE telegram_id=? AND job_type='tts' ORDER BY id DESC LIMIT 10",
        (message.from_user.id,),
    )
    if not rows:
        await send_ui(message, "Готовых аудио-задач пока нет.")
        return
    for row in rows:
        await send_ui(message, format_job(dict(row)), reply_markup=job_history_keyboard(row["id"], row["job_type"], bool(row["local_result_path"])))


@router.message(F.text.in_({"Выбрать video model", "Выбрать avatar model", "Выбрать image model"}))
async def choose_model_menu(message: Message, db: Database, settings: Settings, models: ModelService) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    if message.from_user.id != settings.admin_telegram_id:
        await send_ui(message, "Модели выбирает администратор. Ты можешь выбрать голос в разделе 🎭 Голос.")
        return
    family = "image" if "image" in message.text else ("avatar" if "avatar" in message.text else "video")
    await show_model_picker(message, db, settings, models, message.from_user.id, family)


@router.callback_query(lambda c: c.data and c.data.startswith("user_model:"))
async def user_model_callback(callback: CallbackQuery, db: Database, settings: Settings, models: ModelService) -> None:
    row = await db.get_user(callback.from_user.id)
    if callback.from_user.id != settings.admin_telegram_id and not (row and row["is_allowed"]):
        await callback.answer("Доступ не выдан.", show_alert=True)
        return
    if callback.from_user.id != settings.admin_telegram_id:
        await callback.answer("Модель выбирает администратор.", show_alert=True)
        return
    _, family, raw_index = callback.data.split(":", 2)
    try:
        index = int(raw_index)
    except ValueError:
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return
    user_settings = await db.get_user_settings(callback.from_user.id)
    compatible = await compatible_models_for_family(models, family, user_settings)
    if index < 1 or index > len(compatible):
        await callback.answer("Модель не найдена. Открой список заново.", show_alert=True)
        return
    model = compatible[index - 1]
    await models.set_user_model(callback.from_user.id, family, model["id"])
    await send_ui(callback.message, f"Выбрана модель:\n{model['name']}\n{model['id']}")
    await callback.answer("Выбрано.")


@router.message(F.text == "Текущие параметры")
async def current_settings(message: Message, db: Database, settings: Settings, models: ModelService) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    user_settings = await db.get_user_settings(message.from_user.id)
    voice = await selected_or_default_voice(db, message.from_user.id)
    avatar = await models.selected_model_for_user(message.from_user.id, "avatar")
    video = await models.selected_model_for_user(message.from_user.id, "video")
    image = await models.selected_model_for_user(message.from_user.id, "image")
    await send_ui(
        message,
        "Текущие параметры\n"
        f"Голос: {(voice or {}).get('name') or 'не выбран'}\n"
        f"Avatar model: {(avatar or {}).get('name') or 'по умолчанию'}\n"
        f"Video model: {(video or {}).get('name') or 'по умолчанию'}\n"
        f"Image model: {(image or {}).get('name') or 'по умолчанию'}\n"
        f"Video: {user_settings['video_aspect_ratio']} / {user_settings['video_resolution']} / {user_settings['video_duration_ms']} ms\n"
        f"Image: {user_settings['image_aspect_ratio']} / {user_settings['image_resolution']}\n"
        f"TTS: speed={user_settings['tts_speed']} stability={user_settings['tts_stability']}"
    )


@router.message(F.text == "Очистить временные результаты")
async def cleanup_user_results(message: Message, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    rows = await db.fetchall("SELECT id FROM jobs WHERE telegram_id=? AND local_result_path IS NOT NULL", (message.from_user.id,))
    removed = 0
    for row in rows:
        if await jobs.delete_local_result(row["id"], message.from_user.id, False):
            removed += 1
    await send_ui(message, f"Локальные временные результаты удалены: {removed}")


@router.message(F.text.in_({"Video aspect ratio", "Video resolution", "Image aspect ratio", "Image resolution", "TTS speed", "TTS stability"}))
async def setting_option_menu(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    options = {
        "Video aspect ratio": ("video_aspect_ratio", ["1:1", "9:16", "16:9"]),
        "Video resolution": ("video_resolution", ["540p", "720p", "1080p"]),
        "Image aspect ratio": ("image_aspect_ratio", ["1:1", "9:16", "16:9"]),
        "Image resolution": ("image_resolution", ["540p", "720p", "1080p"]),
        "TTS speed": ("tts_speed", ["0.7", "0.85", "1.0", "1.1", "1.2"]),
        "TTS stability": ("tts_stability", ["0.0", "0.25", "0.5", "0.75", "1.0"]),
    }[message.text]
    await send_ui(message, f"Выбери значение: {message.text}", reply_markup=options_keyboard(options[0], options[1]))


@router.callback_query(lambda c: c.data and c.data.startswith("option:"))
async def setting_option_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    row = await db.get_user(callback.from_user.id)
    if callback.from_user.id != settings.admin_telegram_id and not (row and row["is_allowed"]):
        await callback.answer("Доступ не выдан.", show_alert=True)
        return
    _, key, value = callback.data.split(":", 2)
    if key in {"tts_speed", "tts_stability"}:
        await db.update_user_settings(callback.from_user.id, **{key: float(value)})
    elif key == "video_duration_ms":
        await db.update_user_settings(callback.from_user.id, **{key: int(value)})
    else:
        await db.update_user_settings(callback.from_user.id, **{key: value})
    await send_ui(callback.message, f"Настройка обновлена: {key} = {value}")
    await callback.answer("Готово.")


def get_image_file_id(message: Message) -> str | None:
    if message.photo:
        return message.photo[-1].file_id
    if message.document and message.document.mime_type in {"image/jpeg", "image/png"}:
        return message.document.file_id
    return None


def get_audio_file_id(message: Message) -> str | None:
    if message.voice:
        return message.voice.file_id
    if message.audio:
        return message.audio.file_id
    if message.document and message.document.mime_type in {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg", "audio/mp3"}:
        return message.document.file_id
    return None


async def selected_or_default_voice(db: Database, telegram_id: int) -> dict | None:
    user = await db.get_user(telegram_id)
    if user and user["selected_voice_id"]:
        row = await db.fetchone(
            "SELECT * FROM voices WHERE hedra_voice_id=? AND is_active=1",
            (user["selected_voice_id"],),
        )
        if row:
            return dict(row)
    row = await db.fetchone("SELECT * FROM voices WHERE is_active=1 AND is_default=1 ORDER BY id LIMIT 1")
    return dict(row) if row else None


async def compatible_models_for_family(models: ModelService, family: str, user_settings) -> list[dict]:
    if family == "avatar":
        return await models.compatible_avatar_models(user_settings["video_aspect_ratio"], user_settings["video_resolution"])
    if family == "video":
        return await models.compatible_video_models(user_settings["video_aspect_ratio"], user_settings["video_resolution"])
    return await models.compatible_image_models(user_settings["image_aspect_ratio"], user_settings["image_resolution"])


async def show_model_picker(message: Message, db: Database, settings: Settings, models: ModelService, telegram_id: int, family: str) -> None:
    user_settings = await db.get_user_settings(telegram_id)
    compatible = await compatible_models_for_family(models, family, user_settings)
    selected = await models.selected_model_for_user(telegram_id, family)
    if not compatible:
        await send_ui(
            message,
            "Совместимые модели не найдены. Попроси админа выполнить /admin_models_sync.\n"
            "Если модель есть в web-интерфейсе Hedra, но не приходит через /models, бот не может использовать её официально."
        )
        return
    label = {"avatar": "avatar", "video": "video", "image": "image"}[family]
    lines = []
    for model in compatible[:12]:
        price = f" credits={model.get('credit_cost')}" if model.get("credit_cost") is not None else ""
        premium = " premium" if model.get("premium") else ""
        lines.append(f"{model['name']}\ntype={model.get('type')} {premium}{price}")
    await send_ui(
        message,
        f"Выбери {label} model:\n\n" + "\n\n".join(lines),
        reply_markup=user_models_keyboard(family, compatible[:12], (selected or {}).get("id")),
    )


async def selected_model_for_job(db: Database, telegram_id: int, family: str) -> dict | None:
    settings_row = await db.get_user_settings(telegram_id)
    model_id = settings_row[f"selected_{family}_model_id"]
    if not model_id:
        model_id = await db.get_setting(f"selected_{family}_model_id")
    if not model_id and family == "avatar":
        model_id = await db.get_setting("selected_video_model_id")
    if not model_id:
        return None
    row = await db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
    return dict(row) if row else None


async def default_prompt_for_scenario(settings: Settings, db: Database, scenario: str) -> str:
    if scenario == "image_to_video":
        return await db.get_setting("default_video_no_audio_prompt") or settings.default_video_no_audio_prompt
    if scenario in {"video_from_text", "video_from_uploaded_audio", "video_from_generated_audio"}:
        return await db.get_setting("default_avatar_prompt") or settings.default_avatar_prompt
    if scenario == "text_to_image":
        return await db.get_setting("default_image_prompt") or settings.default_image_prompt
    if scenario == "image_edit":
        return await db.get_setting("default_image_edit_prompt") or settings.default_image_edit_prompt
    return ""


def format_job(job: dict) -> str:
    text = f"Задача #{job['id']}\nТип: {job['job_type']}\nСтатус: {job['status']}"
    if job.get("voice_name"):
        text += f"\nГолос: {job['voice_name']}"
    if job.get("source_audio_job_id"):
        text += f"\nСоздано из аудио-задачи #{job['source_audio_job_id']}"
    if job.get("error_message"):
        text += f"\nОшибка: {job['error_message']}"
    return text
