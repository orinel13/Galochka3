from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from app.access import ensure_admin
from app.config import Settings
from app.db import Database
from app.files import FileValidationError, FilesService
from app.hedra_client import HedraClient
from app.jobs import JobManager
from app.services.cleanup_service import CleanupService
from app.services.credits_service import CreditsService
from app.services.model_service import ModelService
from app.services.voice_clone_service import VoiceCloneService
from app.states import VoiceCloneState
from app.utils import compact_json, now_iso, short_error

router = Router()


@router.message(Command("admin"))
async def admin_help(message: Message, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    await message.answer(
        "/admin_users\n/admin_allow <telegram_id>\n/admin_deny <telegram_id>\n/admin_revoke <telegram_id>\n"
        "/admin_voices\n/admin_add_voice <name> <hedra_voice_id>\n/admin_disable_voice <hedra_voice_id>\n"
        "/admin_enable_voice <hedra_voice_id>\n/admin_set_default_voice <hedra_voice_id>\n/admin_clone_voice\n"
        "/admin_clone_status\n/admin_models_sync\n/admin_models\n/admin_set_video_model <model_id>\n"
        "/admin_balance\n/admin_jobs\n/admin_job <job_id>\n/admin_cancel_job <job_id>\n"
        "/admin_cleanup\n/admin_export_db\n/admin_hedra_test"
    )


@router.message(Command("admin_users"))
async def admin_users(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await db.fetchall("SELECT * FROM users ORDER BY updated_at DESC LIMIT 50")
    if not rows:
        await message.answer("Пользователей нет.")
        return
    await message.answer("\n\n".join(format_user_row(dict(row)) for row in rows))


@router.message(Command("admin_allow"))
async def admin_allow(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    telegram_id = parse_int_arg(message)
    if not telegram_id:
        await message.answer("Формат: /admin_allow <telegram_id>")
        return
    await db.set_user_allowed(telegram_id, True)
    await message.answer(f"Доступ выдан: {telegram_id}")


@router.message(Command("admin_deny"))
async def admin_deny(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    telegram_id = parse_int_arg(message)
    if not telegram_id:
        await message.answer("Формат: /admin_deny <telegram_id>")
        return
    await db.decide_access(telegram_id, False, settings.admin_telegram_id)
    await message.answer(f"Заявка отклонена: {telegram_id}")


@router.message(Command("admin_revoke"))
async def admin_revoke(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    telegram_id = parse_int_arg(message)
    if not telegram_id:
        await message.answer("Формат: /admin_revoke <telegram_id>")
        return
    await db.set_user_allowed(telegram_id, False)
    await message.answer(f"Доступ отозван: {telegram_id}")


@router.message(Command("admin_voices"))
async def admin_voices(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await db.fetchall("SELECT * FROM voices ORDER BY is_default DESC, name")
    if not rows:
        await message.answer("Голоса не добавлены.")
        return
    await message.answer("\n\n".join(format_voice(dict(row)) for row in rows))


@router.message(Command("admin_add_voice"))
async def admin_add_voice(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    args = command_args(message)
    parts = args.rsplit(" ", 1)
    if len(parts) != 2:
        await message.answer("Формат: /admin_add_voice <name> <hedra_voice_id>")
        return
    name, voice_id = parts[0].strip(), parts[1].strip()
    count = await db.fetchone("SELECT COUNT(*) AS c FROM voices")
    is_default = 1 if count and count["c"] == 0 else 0
    await db.execute(
        """
        INSERT INTO voices (name, hedra_voice_id, source, is_active, is_default, created_at, updated_at)
        VALUES (?, ?, 'manual', 1, ?, ?, ?)
        ON CONFLICT(hedra_voice_id) DO UPDATE SET name=excluded.name, is_active=1, updated_at=excluded.updated_at
        """,
        (name, voice_id, is_default, now_iso(), now_iso()),
    )
    await message.answer(f"Голос добавлен: {name}\nvoice_id: {voice_id}")


@router.message(Command("admin_disable_voice"))
async def admin_disable_voice(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    voice_id = command_args(message).strip()
    if not voice_id:
        await message.answer("Формат: /admin_disable_voice <hedra_voice_id>")
        return
    await db.execute("UPDATE voices SET is_active=0, updated_at=? WHERE hedra_voice_id=?", (now_iso(), voice_id))
    await message.answer("Голос отключён.")


@router.message(Command("admin_enable_voice"))
async def admin_enable_voice(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    voice_id = command_args(message).strip()
    if not voice_id:
        await message.answer("Формат: /admin_enable_voice <hedra_voice_id>")
        return
    await db.execute("UPDATE voices SET is_active=1, updated_at=? WHERE hedra_voice_id=?", (now_iso(), voice_id))
    await message.answer("Голос включён.")


@router.message(Command("admin_set_default_voice"))
async def admin_set_default_voice(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    voice_id = command_args(message).strip()
    if not voice_id:
        await message.answer("Формат: /admin_set_default_voice <hedra_voice_id>")
        return
    await db.execute("UPDATE voices SET is_default=0")
    await db.execute("UPDATE voices SET is_default=1, is_active=1, updated_at=? WHERE hedra_voice_id=?", (now_iso(), voice_id))
    await message.answer("Голос по умолчанию установлен.")


@router.message(Command("admin_clone_voice"))
async def admin_clone_voice(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    await state.set_state(VoiceCloneState.waiting_name)
    await message.answer("Отправь название нового голоса.")


@router.message(VoiceCloneState.waiting_name)
async def admin_clone_name(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не должно быть пустым.")
        return
    await state.update_data(voice_name=name)
    await state.set_state(VoiceCloneState.waiting_audio)
    await message.answer("Пришли audio sample mp3/wav/ogg. После clone локальный sample будет удалён.")


@router.message(VoiceCloneState.waiting_audio)
async def admin_clone_audio(
    message: Message,
    state: FSMContext,
    settings: Settings,
    files: FilesService,
    voice_clone: VoiceCloneService,
) -> None:
    if not await ensure_admin(message, settings):
        return
    data = await state.get_data()
    try:
        sample_path, _ = await files.download_audio(message, 0, convert_voice=True)
    except FileValidationError as exc:
        await message.answer(str(exc))
        return
    await message.answer("Voice clone запущен. Дождись результата.")
    ok, result = await voice_clone.clone_voice(data["voice_name"], sample_path)
    await state.clear()
    await message.answer(result)


@router.message(Command("admin_clone_status"))
async def admin_clone_status(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await db.fetchall("SELECT * FROM voice_clone_jobs ORDER BY id DESC LIMIT 10")
    if not rows:
        await message.answer("Voice clone задач пока нет.")
        return
    await message.answer("\n\n".join(format_clone_job(dict(row)) for row in rows))


@router.message(Command("admin_models_sync"))
async def admin_models_sync(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    try:
        count = await models.sync_models()
        await message.answer(f"Модели синхронизированы: {count}")
    except Exception as exc:
        await message.answer(f"Не удалось синхронизировать модели: {short_error(str(exc))}")


@router.message(Command("admin_models"))
async def admin_models(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await models.list_models()
    selected = await models.selected_video_model_id()
    if not rows:
        await message.answer("Моделей нет. Выполни /admin_models_sync.")
        return
    chunks = []
    for row in rows[:30]:
        mark = " ✅" if row["id"] == selected else ""
        chunks.append(
            f"{row['id']}{mark}\n{row['name']}\ntype={row.get('type')} 1:1={row.get('supports_1_1')} "
            f"540p={row.get('supports_540p')} max_ms={row.get('max_duration_ms')}"
        )
    await message.answer("\n\n".join(chunks))


@router.message(Command("admin_set_video_model"))
async def admin_set_video_model(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    model_id = command_args(message).strip()
    if not model_id:
        await message.answer("Формат: /admin_set_video_model <model_id>")
        return
    if await models.set_video_model(model_id):
        await message.answer(f"Video model выбрана: {model_id}")
    else:
        await message.answer("Модель не найдена. Выполни /admin_models_sync.")


@router.message(Command("admin_balance"))
async def admin_balance(message: Message, settings: Settings, credits: CreditsService) -> None:
    if not await ensure_admin(message, settings):
        return
    data = await credits.get_credits(save_snapshot=True)
    await message.answer(f"Баланс Hedra:\n{compact_json(data, 1500)}")


@router.message(Command("admin_jobs"))
async def admin_jobs(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await db.fetchall("SELECT * FROM jobs ORDER BY id DESC LIMIT 20")
    if not rows:
        await message.answer("Задач пока нет.")
        return
    await message.answer("\n\n".join(format_job_admin(dict(row)) for row in rows))


@router.message(Command("admin_job"))
async def admin_job(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    job_id = parse_int_arg(message)
    if not job_id:
        await message.answer("Формат: /admin_job <job_id>")
        return
    row = await db.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
    await message.answer(format_job_admin(dict(row)) if row else "Задача не найдена.")


@router.message(Command("admin_cancel_job"))
async def admin_cancel_job(message: Message, settings: Settings, jobs: JobManager) -> None:
    if not await ensure_admin(message, settings):
        return
    job_id = parse_int_arg(message)
    if not job_id:
        await message.answer("Формат: /admin_cancel_job <job_id>")
        return
    ok = await jobs.cancel_job(job_id)
    await message.answer("Задача отменена." if ok else "Не удалось отменить задачу.")


@router.message(Command("admin_cleanup"))
async def admin_cleanup(message: Message, settings: Settings, cleanup: CleanupService) -> None:
    if not await ensure_admin(message, settings):
        return
    removed = await cleanup.run_once()
    await message.answer(f"Cleanup завершён. Удалено файлов: {removed}")


@router.message(Command("admin_export_db"))
async def admin_export_db(message: Message, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    path = settings.database_path
    if not path.exists():
        await message.answer("База данных не найдена.")
        return
    await message.answer_document(FSInputFile(path), caption="SQLite backup")


@router.message(Command("admin_hedra_test"))
async def admin_hedra_test(
    message: Message,
    db: Database,
    settings: Settings,
    hedra: HedraClient,
    credits: CreditsService,
    models: ModelService,
) -> None:
    if not await ensure_admin(message, settings):
        return
    lines = []
    try:
        credit_data = await hedra.get_credits()
        lines.append("API key: работает")
        lines.append(f"credits: {credits.remaining(credit_data)}")
    except Exception as exc:
        lines.append(f"API key/credits: ошибка: {short_error(str(exc))}")
    try:
        voices = await hedra.list_voices()
        lines.append(f"voices: {len(voices)}")
    except Exception as exc:
        lines.append(f"voices: ошибка: {short_error(str(exc))}")
    try:
        api_models = await hedra.list_models()
        lines.append(f"models: {len(api_models)}")
    except Exception as exc:
        lines.append(f"models: ошибка: {short_error(str(exc))}")
    lines.append(f"selected video model: {await models.selected_video_model_id() or 'не выбрана'}")
    default_voice = await db.fetchone("SELECT * FROM voices WHERE is_default=1 LIMIT 1")
    lines.append(f"default voice: {default_voice['name'] if default_voice else 'не выбран'}")
    await message.answer("\n".join(lines))


def command_args(message: Message) -> str:
    text = message.text or ""
    return text.split(" ", 1)[1].strip() if " " in text else ""


def parse_int_arg(message: Message) -> int | None:
    try:
        return int(command_args(message).split()[0])
    except (ValueError, IndexError):
        return None


def format_user_row(row: dict) -> str:
    return (
        f"{row['telegram_id']} @{row.get('username') or '-'}\n"
        f"allowed={row['is_allowed']} admin={row['is_admin']}\n"
        f"{row.get('first_name') or ''} {row.get('last_name') or ''}"
    )


def format_voice(row: dict) -> str:
    return (
        f"{row['name']}\nvoice_id={row['hedra_voice_id']}\n"
        f"active={row['is_active']} default={row['is_default']} source={row['source']}"
    )


def format_clone_job(row: dict) -> str:
    return (
        f"Clone #{row['id']} {row['name']}\nstatus={row['status']}\n"
        f"generation={row.get('hedra_generation_id')}\nvoice_id={row.get('resulting_voice_id')}\n"
        f"error={row.get('error_message') or '-'}"
    )


def format_job_admin(row: dict) -> str:
    return (
        f"Job #{row['id']} user={row['telegram_id']}\n"
        f"type={row['job_type']} status={row['status']}\n"
        f"generation={row.get('hedra_generation_id') or '-'}\n"
        f"source_audio={row.get('source_audio_job_id') or '-'}\n"
        f"error={row.get('error_message') or '-'}"
    )
