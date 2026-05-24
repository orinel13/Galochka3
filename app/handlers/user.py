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
    AUDIO_PHOTO_TO_VIDEO,
    BALANCE,
    HELP,
    MY_JOBS,
    TEXT_PHOTO_TO_VIDEO,
    TEXT_TO_AUDIO,
    VOICE_MENU,
    choose_voice_keyboard,
    job_history_keyboard,
    main_menu,
    voices_keyboard,
)
from app.models import JobType
from app.services.credits_service import CreditsService
from app.states import AudioPhotoVideoState, GeneratedAudioVideoState, TextPhotoVideoState, TextToAudioState
from app.utils import now_iso, short_error

router = Router()


@router.message(Command("help"))
@router.message(F.text == HELP)
async def help_message(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await message.answer(
        "Доступные действия:\n"
        "🎙 Текст → аудио\n"
        "🖼 Текст + фото → видео\n"
        "🎧 Аудио + фото → видео\n"
        "🎭 Голос\n"
        "📊 Баланс\n"
        "🕘 Мои задачи",
        reply_markup=main_menu(),
    )


@router.message(F.text == TEXT_TO_AUDIO)
async def text_to_audio_start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await state.set_state(TextToAudioState.waiting_text)
    await message.answer("Отправь текст для озвучки.")


@router.message(TextToAudioState.waiting_text)
async def text_to_audio_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришли текст сообщением.")
        return
    if len(text) > settings.max_text_chars_tts:
        await message.answer(f"Текст слишком длинный. Лимит: {settings.max_text_chars_tts} символов.")
        return
    voice = await selected_or_default_voice(db, message.from_user.id)
    if not voice:
        await message.answer(
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
    await message.answer(f"Задача #{job_id} поставлена в очередь.")


@router.message(F.text == TEXT_PHOTO_TO_VIDEO)
async def text_photo_video_start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await state.set_state(TextPhotoVideoState.waiting_photo)
    await message.answer("Пришли фото для видео.")


@router.message(TextPhotoVideoState.waiting_photo)
async def text_photo_video_photo(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await message.answer("Пришли фото JPG или PNG.")
        return
    await state.update_data(image_file_id=file_id)
    await state.set_state(TextPhotoVideoState.waiting_text)
    await message.answer("Теперь отправь текст для видео.")


@router.message(TextPhotoVideoState.waiting_text)
async def text_photo_video_text(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришли текст сообщением.")
        return
    if len(text) > settings.max_text_chars_video:
        await message.answer(f"Текст слишком длинный. Лимит: {settings.max_text_chars_video} символов.")
        return
    voice = await selected_or_default_voice(db, message.from_user.id)
    if not voice:
        await message.answer(
            "Голос не выбран. Выбери голос из списка.",
            reply_markup=choose_voice_keyboard(),
        )
        return
    data = await state.get_data()
    job_id = await jobs.create_job(
        telegram_id=message.from_user.id,
        job_type=JobType.VIDEO_FROM_TEXT.value,
        text=text,
        voice_id=voice["hedra_voice_id"],
        voice_name=voice["name"],
        image_file_id=data["image_file_id"],
    )
    await state.clear()
    await message.answer(f"Задача #{job_id} поставлена в очередь.")


@router.message(F.text == AUDIO_PHOTO_TO_VIDEO)
async def audio_photo_video_start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    await state.set_state(AudioPhotoVideoState.waiting_photo)
    await message.answer("Пришли фото для видео.")


@router.message(AudioPhotoVideoState.waiting_photo)
async def audio_photo_video_photo(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await message.answer("Пришли фото JPG или PNG.")
        return
    await state.update_data(image_file_id=file_id)
    await state.set_state(AudioPhotoVideoState.waiting_audio)
    await message.answer("Теперь пришли аудио, voice или audio-документ mp3/wav/ogg.")


@router.message(AudioPhotoVideoState.waiting_audio)
async def audio_photo_video_audio(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    audio_file_id = get_audio_file_id(message)
    if not audio_file_id:
        await message.answer("Пришли аудио, voice или audio-документ mp3/wav/ogg.")
        return
    data = await state.get_data()
    job_id = await jobs.create_job(
        telegram_id=message.from_user.id,
        job_type=JobType.VIDEO_FROM_UPLOADED_AUDIO.value,
        image_file_id=data["image_file_id"],
        audio_file_id=audio_file_id,
    )
    await state.clear()
    await message.answer(f"Задача #{job_id} поставлена в очередь.")


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
        await callback.message.answer("Аудиофайл уже очищен. Сгенерируй аудио заново.")
        await callback.answer()
        return
    await state.set_state(GeneratedAudioVideoState.waiting_photo)
    await state.update_data(source_audio_job_id=job_id)
    await callback.message.answer("Пришли фото для видео из этого аудио.")
    await callback.answer()


@router.message(GeneratedAudioVideoState.waiting_photo)
async def generated_audio_video_photo(message: Message, state: FSMContext, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    file_id = get_image_file_id(message)
    if not file_id:
        await message.answer("Пришли фото JPG или PNG.")
        return
    data = await state.get_data()
    source_job_id = int(data["source_audio_job_id"])
    source = await db.fetchone("SELECT * FROM jobs WHERE id=?", (source_job_id,))
    job_id = await jobs.create_job(
        telegram_id=message.from_user.id,
        job_type=JobType.VIDEO_FROM_GENERATED_AUDIO.value,
        parent_job_id=source_job_id,
        source_audio_job_id=source_job_id,
        voice_id=source["voice_id"] if source else None,
        voice_name=source["voice_name"] if source else None,
        source_image_file_id=file_id,
    )
    await state.clear()
    await message.answer(f"Задача #{job_id} поставлена в очередь.")


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
    await callback.message.answer(f"Задача #{job_id} поставлена в очередь.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("delete_result:"))
async def delete_result(callback: CallbackQuery, db: Database, settings: Settings, jobs: JobManager) -> None:
    if not callback.from_user:
        return
    admin = callback.from_user.id == settings.admin_telegram_id
    job_id = int(callback.data.split(":", 1)[1])
    ok = await jobs.delete_local_result(job_id, callback.from_user.id, admin)
    await callback.message.answer("Локальный файл результата удалён." if ok else "Задача недоступна.")
    await callback.answer()


@router.message(Command("voices"))
@router.message(F.text == VOICE_MENU)
async def voices(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    rows = await db.fetchall("SELECT name, hedra_voice_id FROM voices WHERE is_active=1 ORDER BY is_default DESC, name")
    if not rows:
        await message.answer("Активных голосов пока нет. Попроси администратора добавить voice_id.")
        return
    text = "Активные голоса:\n" + "\n".join(f"• {row['name']}" for row in rows)
    await message.answer(text, reply_markup=voices_keyboard([dict(row) for row in rows]))


@router.message(Command("setvoice"))
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
        await message.answer("Активных голосов пока нет.")
    else:
        await message.answer("Выбери голос:", reply_markup=voices_keyboard([dict(row) for row in rows]))
    if isinstance(event, CallbackQuery):
        await event.answer()


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
    await callback.message.answer(f"Выбран голос: {row['name']}")
    await callback.answer()


@router.message(Command("balance"))
@router.message(F.text == BALANCE)
async def balance(message: Message, db: Database, settings: Settings, credits: CreditsService) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    try:
        data = await credits.get_credits(save_snapshot=False)
        remaining = credits.remaining(data)
        await message.answer(f"Hedra credits: {remaining if remaining is not None else 'не удалось определить'}")
    except Exception as exc:
        await message.answer(f"Не удалось получить баланс: {short_error(str(exc))}")


@router.message(F.text == MY_JOBS)
async def my_jobs(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_allowed(message, db, settings):
        return
    rows = await db.fetchall(
        "SELECT * FROM jobs WHERE telegram_id=? ORDER BY id DESC LIMIT 10",
        (message.from_user.id,),
    )
    if not rows:
        await message.answer("Задач пока нет.")
        return
    for row in rows:
        text = format_job(dict(row))
        await message.answer(text, reply_markup=job_history_keyboard(row["id"], row["job_type"], bool(row["local_result_path"])))


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


def format_job(job: dict) -> str:
    text = f"Задача #{job['id']}\nТип: {job['job_type']}\nСтатус: {job['status']}"
    if job.get("voice_name"):
        text += f"\nГолос: {job['voice_name']}"
    if job.get("source_audio_job_id"):
        text += f"\nСоздано из аудио-задачи #{job['source_audio_job_id']}"
    if job.get("error_message"):
        text += f"\nОшибка: {job['error_message']}"
    return text
