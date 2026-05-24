from __future__ import annotations

from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.access import ensure_admin
from app.config import Settings
from app.db import Database
from app.files import FileValidationError, FilesService
from app.hedra_client import HedraClient
from app.jobs import JobManager
from app.keyboards import video_models_keyboard
from app.services.cleanup_service import CleanupService
from app.services.credits_service import CreditsService
from app.services.model_service import (
    ModelService,
    is_avatar_compatible,
    is_image_to_video_compatible,
    supports_image_edit_model,
    supports_text_to_image_model,
)
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
        "/admin_voices\n/admin_hedra_voices [поиск]\n/admin_hedra_voice_assets [поиск]\n"
        "/admin_find_voice <name>\n/admin_import_voice_name <name>\n"
        "/admin_voices_sync\n/admin_voices_sync_all\n/admin_voices_cleanup\n"
        "/admin_add_voice <name> <hedra_voice_id>\n/admin_disable_voice <hedra_voice_id>\n"
        "/admin_enable_voice <hedra_voice_id>\n/admin_set_default_voice <hedra_voice_id>\n/admin_clone_voice\n"
        "/admin_clone_status\n/admin_models_sync\n/admin_models\n/admin_models_image\n/admin_models_video\n/admin_models_avatar\n"
        "/admin_set_avatar_model <model_id>\n/admin_set_video_model <model_id>\n/admin_set_image_model <model_id>\n"
        "/admin_model <model_id>\n/admin_test_model <model_id>\n"
        "/admin_set_omnia_model\n/admin_set_character3_model\n"
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
    await send_long_text(message, "\n\n".join(format_voice(dict(row)) for row in rows))


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
    if not is_uuid(voice_id):
        await message.answer(
            "Это не Hedra voice_id. Hedra ждёт UUID вида xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.\n"
            "Выполни /admin_hedra_voices, скопируй реальный id и добавь его."
        )
        return
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


@router.message(Command("admin_hedra_voices"))
async def admin_hedra_voices(message: Message, settings: Settings, hedra: HedraClient) -> None:
    if not await ensure_admin(message, settings):
        return
    try:
        voices = await hedra.list_voices()
    except Exception as exc:
        await message.answer(f"Не удалось получить голоса Hedra: {short_error(str(exc))}")
        return
    if not voices:
        await message.answer("Hedra не вернула доступные голоса.")
        return
    query = command_args(message).strip().lower()
    if query:
        voices = [voice for voice in voices if voice_matches(voice, query)]
        if not voices:
            await message.answer(
                "Hedra API не вернул голос с таким именем.\n"
                "Проверь, что HEDRA_API_KEY создан в том же аккаунте/workspace, где голос виден в браузере."
            )
            return
    chunks = []
    for voice in voices:
        name = extract_voice_name(voice)
        voice_id = extract_voice_id(voice)
        description = str(voice.get("description") or "").strip()
        custom_mark = "custom" if is_custom_voice(voice) else "library"
        suffix = f"\n{description}" if description else ""
        chunks.append(f"{name}\n{voice_id or 'id не найден'}\n{custom_mark}{suffix}")
    header = f"Голоса Hedra: {len(voices)}"
    if query:
        header += f"\nПоиск: {query}"
    await send_long_text(message, header + "\n\n" + "\n\n".join(chunks))


@router.message(Command("admin_find_voice"))
async def admin_find_voice(message: Message, settings: Settings, hedra: HedraClient) -> None:
    if not await ensure_admin(message, settings):
        return
    query = command_args(message).strip()
    if not query:
        await message.answer("Формат: /admin_find_voice <name>")
        return
    voices, voice_assets = await load_voice_sources(hedra)
    matches = [("voices", voice) for voice in voices if voice_matches(voice, query.lower())]
    matches += [("assets?type=voice", voice) for voice in voice_assets if voice_matches(voice, query.lower())]
    if not matches:
        await message.answer(
            f"Голос '{query}' не найден ни в /voices, ни в /assets?type=voice.\n"
            "Если он виден в браузере, public API key сейчас не имеет доступа к этому voice asset "
            "или UI хранит этот ElevenLabs V3 голос вне public API."
        )
        return
    chunks = [
        f"{source}\n{extract_voice_name(voice)}\n{extract_voice_id(voice) or 'id не найден'}\n"
        f"{'custom' if is_custom_voice(voice) else 'library'}\n{voice_note(voice) or '-'}"
        for source, voice in matches
    ]
    await send_long_text(message, f"Найдено: {len(matches)}\n\n" + "\n\n".join(chunks))


@router.message(Command("admin_import_voice_name"))
async def admin_import_voice_name(message: Message, db: Database, settings: Settings, hedra: HedraClient) -> None:
    if not await ensure_admin(message, settings):
        return
    query = command_args(message).strip()
    if not query:
        await message.answer("Формат: /admin_import_voice_name <name>")
        return
    try:
        voices, voice_assets = await load_voice_sources(hedra)
    except Exception as exc:
        await message.answer(f"Не удалось получить голоса Hedra: {short_error(str(exc))}")
        return
    all_voices = [*voices, *voice_assets]
    exact = [voice for voice in all_voices if extract_voice_name(voice).lower() == query.lower()]
    matches = exact or [voice for voice in all_voices if voice_matches(voice, query.lower())]
    if not matches:
        await message.answer(
            f"Голос '{query}' не найден в ответе Hedra API.\n"
            "Если он виден в браузере, вероятно HEDRA_API_KEY создан не в том аккаунте/workspace "
            "или public API не отдаёт этот тип голоса."
        )
        return
    if len(matches) > 1 and not exact:
        chunks = [
            f"{extract_voice_name(voice)}\n{extract_voice_id(voice) or 'id не найден'}\n"
            f"{'custom' if is_custom_voice(voice) else 'library'}"
            for voice in matches[:20]
        ]
        await send_long_text(message, "Найдено несколько голосов. Уточни имя:\n\n" + "\n\n".join(chunks))
        return
    voice = matches[0]
    voice_id = extract_voice_id(voice)
    if not voice_id or not is_uuid(voice_id):
        await message.answer("Hedra вернула голос без UUID, импорт невозможен.")
        return
    name = extract_voice_name(voice)
    count = await db.fetchone("SELECT COUNT(*) AS c FROM voices")
    is_default = 1 if count and count["c"] == 0 else 0
    source = "hedra_api_custom" if is_custom_voice(voice) else "hedra_api_library"
    await db.execute(
        """
        INSERT INTO voices (name, hedra_voice_id, source, is_active, is_default, notes, created_at, updated_at)
        VALUES (?, ?, ?, 1, ?, ?, ?, ?)
        ON CONFLICT(hedra_voice_id) DO UPDATE SET
          name=excluded.name,
          source=excluded.source,
          is_active=1,
          notes=excluded.notes,
          updated_at=excluded.updated_at
        """,
        (name, voice_id, source, is_default, voice_note(voice), now_iso(), now_iso()),
    )
    await message.answer(f"Голос импортирован: {name}\nvoice_id: {voice_id}")


@router.message(Command("admin_hedra_voice_assets"))
async def admin_hedra_voice_assets(message: Message, settings: Settings, hedra: HedraClient) -> None:
    if not await ensure_admin(message, settings):
        return
    query = command_args(message).strip().lower()
    try:
        assets = await hedra.list_assets("voice")
    except Exception as exc:
        await message.answer(f"Не удалось получить /assets?type=voice: {short_error(str(exc))}")
        return
    if query:
        assets = [asset for asset in assets if voice_matches(asset, query)]
    if not assets:
        await message.answer("Voice assets не найдены.")
        return
    chunks = []
    for asset in assets:
        chunks.append(
            f"{extract_voice_name(asset)}\n{extract_voice_id(asset) or 'id не найден'}\n"
            f"{'custom' if is_custom_voice(asset) else 'library'}\n{voice_note(asset) or '-'}"
        )
    await send_long_text(message, f"Voice assets: {len(assets)}\n\n" + "\n\n".join(chunks))


@router.message(Command("admin_voices_sync"))
async def admin_voices_sync(message: Message, db: Database, settings: Settings, hedra: HedraClient) -> None:
    if not await ensure_admin(message, settings):
        return
    try:
        voices = await hedra.list_voices()
    except Exception as exc:
        await message.answer(f"Не удалось получить голоса Hedra: {short_error(str(exc))}")
        return
    imported = 0
    skipped = 0
    skipped_library = 0
    for voice in voices:
        if not is_custom_voice(voice):
            skipped_library += 1
            continue
        voice_id = extract_voice_id(voice)
        if not voice_id or not is_uuid(voice_id):
            skipped += 1
            continue
        name = extract_voice_name(voice)
        count = await db.fetchone("SELECT COUNT(*) AS c FROM voices")
        is_default = 1 if count and count["c"] == 0 else 0
        await db.execute(
            """
            INSERT INTO voices (name, hedra_voice_id, source, is_active, is_default, notes, created_at, updated_at)
            VALUES (?, ?, 'hedra_api_custom', 1, ?, ?, ?, ?)
            ON CONFLICT(hedra_voice_id) DO UPDATE SET
              name=excluded.name,
              source=excluded.source,
              is_active=1,
              notes=excluded.notes,
              updated_at=excluded.updated_at
            """,
            (name, voice_id, is_default, voice_note(voice), now_iso(), now_iso()),
        )
        imported += 1
    await message.answer(
        f"Мои голоса синхронизированы: {imported}.\n"
        f"Пропущено библиотечных: {skipped_library}.\n"
        f"Пропущено без UUID: {skipped}."
    )


@router.message(Command("admin_voices_sync_all"))
async def admin_voices_sync_all(message: Message, db: Database, settings: Settings, hedra: HedraClient) -> None:
    if not await ensure_admin(message, settings):
        return
    try:
        voices = await hedra.list_voices()
    except Exception as exc:
        await message.answer(f"Не удалось получить голоса Hedra: {short_error(str(exc))}")
        return
    imported = 0
    skipped = 0
    for voice in voices:
        voice_id = extract_voice_id(voice)
        if not voice_id or not is_uuid(voice_id):
            skipped += 1
            continue
        name = extract_voice_name(voice)
        source = "hedra_api_custom" if is_custom_voice(voice) else "hedra_api_library"
        count = await db.fetchone("SELECT COUNT(*) AS c FROM voices")
        is_default = 1 if count and count["c"] == 0 else 0
        await db.execute(
            """
            INSERT INTO voices (name, hedra_voice_id, source, is_active, is_default, notes, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(hedra_voice_id) DO UPDATE SET
              name=excluded.name,
              source=excluded.source,
              is_active=1,
              notes=excluded.notes,
              updated_at=excluded.updated_at
            """,
            (name, voice_id, source, is_default, voice_note(voice), now_iso(), now_iso()),
        )
        imported += 1
    await message.answer(f"Все голоса Hedra синхронизированы: {imported}. Пропущено без UUID: {skipped}.")


@router.message(Command("admin_voices_cleanup"))
async def admin_voices_cleanup(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    await db.execute("UPDATE voices SET is_active=0, is_default=0, updated_at=? WHERE hedra_voice_id NOT LIKE '%-%'", (now_iso(),))
    await db.execute(
        "UPDATE voices SET is_active=0, is_default=0, updated_at=? WHERE source IN ('hedra_api', 'hedra_api_library')",
        (now_iso(),),
    )
    await db.execute("UPDATE users SET selected_voice_id=NULL, selected_voice_name=NULL, updated_at=?", (now_iso(),))
    await message.answer("Голоса очищены: не-UUID и библиотечные голоса отключены. Выбор пользователей сброшен.")


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
    if not is_uuid(voice_id):
        await message.answer("Это не Hedra voice_id UUID. Выполни /admin_hedra_voices и скопируй реальный id.")
        return
    row = await db.fetchone("SELECT hedra_voice_id FROM voices WHERE hedra_voice_id=?", (voice_id,))
    if not row:
        await message.answer("Голос не найден в базе. Сначала добавь его через /admin_add_voice или /admin_voices_sync.")
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
    rows = await models.list_avatar_video_models()
    selected = await models.selected_video_model_id()
    if not rows:
        await message.answer("Моделей нет. Выполни /admin_models_sync.")
        return
    chunks = []
    for row in rows[:12]:
        mark = " ✅" if row["id"] == selected else ""
        chunks.append(
            f"{row['id']}{mark}\n{row['name']}\ntype={row.get('type')} 1:1={row.get('supports_1_1')} "
            f"540p={row.get('supports_540p')} max_ms={row.get('max_duration_ms')}"
        )
    await message.answer(
        "Video/avatar модели:\n\n" + "\n\n".join(chunks),
        reply_markup=video_models_keyboard(rows[:12], selected),
    )


@router.message(Command("admin_models_avatar"))
async def admin_models_avatar(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await models.compatible_avatar_models()
    await send_long_text(message, format_model_list("Avatar models", rows))


@router.message(Command("admin_models_video"))
async def admin_models_video(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await models.compatible_video_models()
    await send_long_text(message, format_model_list("Video models", rows))


@router.message(Command("admin_models_image"))
async def admin_models_image(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    rows = await models.compatible_image_models()
    await send_long_text(message, format_model_list("Image models", rows))


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


@router.message(Command("admin_set_avatar_model"))
async def admin_set_avatar_model(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    await set_global_model_from_command(message, db, "avatar")


@router.message(Command("admin_set_image_model"))
async def admin_set_image_model(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    await set_global_model_from_command(message, db, "image")


@router.message(Command("admin_model"))
async def admin_model(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    model_id = command_args(message).strip()
    if not model_id:
        await message.answer("Формат: /admin_model <model_id>")
        return
    row = await db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
    if not row:
        await message.answer("Модель не найдена.")
        return
    data = dict(row)
    await send_long_text(
        message,
        format_model_list("Model", [data]) + "\n\nraw_json:\n" + compact_json(data.get("raw_json"), 2500),
    )


@router.message(Command("admin_test_model"))
async def admin_test_model(message: Message, db: Database, settings: Settings) -> None:
    if not await ensure_admin(message, settings):
        return
    model_id = command_args(message).strip()
    if not model_id:
        await message.answer("Формат: /admin_test_model <model_id>")
        return
    row = await db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
    if not row:
        await message.answer("Модель не найдена.")
        return
    model = dict(row)
    image_payload = ["type", "text_prompt", "ai_model_id", "aspect_ratio", "resolution", "batch_size", "enhance_prompt"]
    edit_payload = ["type=image_to_image", "text_prompt", "ai_model_id", "reference_image_ids", "aspect_ratio", "resolution", "batch_size"]
    if model.get("requires_image_url"):
        edit_payload.append("image_urls/image_url")
    elif model.get("supports_image_asset_id"):
        edit_payload.append("image_id/reference_image_ids")
    video_payload = ["type", "ai_model_id", "start_keyframe_id", "generated_video_inputs.aspect_ratio", "generated_video_inputs.resolution", "generated_video_inputs.duration_ms"]
    avatar_payload = ["type", "ai_model_id", "start_keyframe_id", "audio_id/audio_generation", "generated_video_inputs"]
    await message.answer(
        f"{model['name']}\n{model['id']}\n\n"
        f"text_to_image: {supports_text_to_image_model(model)}\n"
        f"image_edit: {supports_image_edit_model(model)}\n"
        f"image_to_video: {is_image_to_video_compatible(model)}\n"
        f"avatar_video: {is_avatar_compatible(model)}\n\n"
        f"text_to_image payload: {', '.join(image_payload)}\n"
        f"image_edit payload: {', '.join(edit_payload)}\n"
        f"image_to_video payload: {', '.join(video_payload)}\n"
        f"avatar_video payload: {', '.join(avatar_payload)}"
    )


@router.callback_query(lambda c: c.data and c.data.startswith("set_video_model:"))
async def set_video_model_callback(callback: CallbackQuery, settings: Settings, models: ModelService) -> None:
    if not callback.from_user or callback.from_user.id != settings.admin_telegram_id:
        await callback.answer("Недоступно.", show_alert=True)
        return
    try:
        index = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return
    rows = await models.list_avatar_video_models()
    if index < 1 or index > len(rows):
        await callback.answer("Модель не найдена. Обнови /admin_models.", show_alert=True)
        return
    model_id = rows[index - 1]["id"]
    if await models.set_video_model(model_id):
        await callback.message.answer(f"Video model выбрана:\n{rows[index - 1]['name']}\n{model_id}")
        await callback.answer("Выбрано.")
    else:
        await callback.answer("Модель не найдена.", show_alert=True)


@router.message(Command("admin_set_omnia_model"))
async def admin_set_omnia_model(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    chosen = await models.set_preferred_by_name("omnia")
    if not chosen:
        await message.answer("Hedra Omnia не найдена. Выполни /admin_models_sync и /admin_models.")
        return
    await message.answer(f"Выбрана Hedra Omnia:\n{chosen['name']}\n{chosen['id']}")


@router.message(Command("admin_set_character3_model"))
async def admin_set_character3_model(message: Message, settings: Settings, models: ModelService) -> None:
    if not await ensure_admin(message, settings):
        return
    chosen = await models.set_preferred_by_name("character 3")
    if not chosen:
        await message.answer("Hedra Character 3 не найдена. Выполни /admin_models_sync и /admin_models.")
        return
    await message.answer(f"Выбрана Hedra Character 3:\n{chosen['name']}\n{chosen['id']}")


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


def is_uuid(value: str) -> bool:
    try:
        UUID(value.removeprefix("urn:uuid:"))
        return True
    except ValueError:
        return False


def extract_voice_id(voice: dict) -> str | None:
    for key in ("id", "voice_id", "hedra_voice_id", "uuid"):
        value = voice.get(key)
        if value:
            return str(value)
    nested = voice.get("voice")
    if isinstance(nested, dict):
        return extract_voice_id(nested)
    return None


def extract_voice_name(voice: dict) -> str:
    for key in ("name", "display_name", "label", "title"):
        value = voice.get(key)
        if value:
            return str(value)
    voice_id = extract_voice_id(voice)
    return voice_id or "Без названия"


async def load_voice_sources(hedra: HedraClient) -> tuple[list[dict], list[dict]]:
    voices = await hedra.list_voices()
    try:
        voice_assets = await hedra.list_assets("voice")
    except Exception:
        voice_assets = []
    return voices, voice_assets


def voice_matches(voice: dict, query: str) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            extract_voice_name(voice),
            extract_voice_id(voice),
            voice.get("description"),
            voice.get("source"),
            voice.get("provider"),
            voice.get("category"),
            voice.get("origin"),
            voice.get("type"),
        )
    ).lower()
    return query.lower() in haystack


def is_custom_voice(voice: dict) -> bool:
    text = " ".join(
        str(voice.get(key) or "")
        for key in ("description", "source", "provider", "category", "origin", "type")
    ).lower()
    name = extract_voice_name(voice).lower()
    if any(marker in text for marker in ("created by user", "user-created", "user created", "custom", "cloned")):
        return True
    if "создан" in text and "пользовател" in text:
        return True
    if text.strip() in {"", "voice"} and name not in {"alice", "daniel"}:
        return False
    return False


def voice_note(voice: dict) -> str:
    description = str(voice.get("description") or "").strip()
    provider = str(voice.get("provider") or "").strip()
    bits = [part for part in (description, provider) if part]
    return " | ".join(bits)[:500] if bits else ""


async def send_long_text(message: Message, text: str, limit: int = 3500) -> None:
    if len(text) <= limit:
        await message.answer(text)
        return
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            if current:
                await message.answer(current)
            current = block
        else:
            current = candidate
    if current:
        await message.answer(current)


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
    text = (
        f"Job #{row['id']} user={row['telegram_id']}\n"
        f"type={row['job_type']} status={row['status']}\n"
        f"generation={row.get('hedra_generation_id') or '-'}\n"
        f"source_audio={row.get('source_audio_job_id') or '-'}\n"
        f"model={row.get('selected_model_name') or row.get('selected_model_id') or '-'}\n"
        f"duration_ms={row.get('duration_ms') or '-'} adapter={row.get('adapter_name') or '-'}\n"
        f"payload_keys={row.get('request_payload_keys') or '-'}\n"
        f"error={row.get('error_message') or '-'}"
    )
    if row.get("hedra_error_raw"):
        text += f"\nhedra_error_raw={str(row['hedra_error_raw'])[:1500]}"
    return text


def format_model_list(title: str, rows: list[dict]) -> str:
    if not rows:
        return f"{title}: не найдены. Выполни /admin_models_sync."
    chunks = []
    for row in rows[:50]:
        chunks.append(
            f"{row['name']}\n{row['id']}\n"
            f"type={row.get('type')} 1:1={row.get('supports_1_1')} 9:16={row.get('supports_9_16')} 16:9={row.get('supports_16_9')}\n"
            f"540p={row.get('supports_540p')} 720p={row.get('supports_720p')} 1080p={row.get('supports_1080p')}\n"
            f"duration_required={row.get('requires_duration_ms')} durations={row.get('allowed_duration_ms_json') or '-'} "
            f"min={row.get('min_duration_ms')} max={row.get('max_duration_ms')} default={row.get('default_duration_ms')}\n"
            f"premium={row.get('premium')} requires_audio={row.get('requires_audio_input')} start_frame={row.get('requires_start_frame')}\n"
            f"text2image={row.get('supports_text_to_image')} image_edit={row.get('supports_image_edit')} "
            f"image_url={row.get('requires_image_url')} asset_id={row.get('supports_image_asset_id')} data_uri={row.get('supports_data_uri')}"
        )
    return title + "\n\n" + "\n\n".join(chunks)


async def set_global_model_from_command(message: Message, db: Database, family: str) -> None:
    model_id = command_args(message).strip()
    if not model_id:
        await message.answer(f"Формат: /admin_set_{family}_model <model_id>")
        return
    row = await db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
    if not row:
        await message.answer("Модель не найдена. Выполни /admin_models_sync.")
        return
    await db.set_setting(f"selected_{family}_model_id", row["id"])
    await db.set_setting(f"selected_{family}_model_name", row["name"])
    if family == "avatar":
        await db.set_setting("selected_video_model_id", row["id"])
        await db.set_setting("selected_video_model_name", row["name"])
    await message.answer(f"Выбрана {family} model:\n{row['name']}\n{row['id']}")
