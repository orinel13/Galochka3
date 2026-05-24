from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import Settings
from app.db import Database
from app.files import FilesService
from app.hedra_client import HedraApiError, HedraClient
from app.keyboards import audio_result_keyboard
from app.models import AUDIO_JOB_TYPES, VIDEO_JOB_TYPES, JobStatus, JobType
from app.services.credits_service import CreditsService
from app.services.model_service import ModelService
from app.services.tts_service import TtsService
from app.services.video_service import VideoService
from app.services.voice_clone_service import extract_id
from app.utils import iso_after_hours, now_iso, short_error

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        bot: Bot,
        hedra: HedraClient,
        files: FilesService,
        model_service: ModelService,
        credits_service: CreditsService,
    ) -> None:
        self.db = db
        self.settings = settings
        self.bot = bot
        self.hedra = hedra
        self.files = files
        self.model_service = model_service
        self.credits_service = credits_service
        self.tts = TtsService(hedra, settings)
        self.video = VideoService(hedra, settings)
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.audio_sem = asyncio.Semaphore(settings.max_parallel_audio_jobs)
        self.video_sem = asyncio.Semaphore(settings.max_parallel_video_jobs)
        self.workers: list[asyncio.Task[None]] = []
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        await self._mark_interrupted_jobs()
        rows = await self.db.fetchall("SELECT id FROM jobs WHERE status='queued' ORDER BY id")
        for row in rows:
            await self.queue.put(row["id"])
        worker_count = max(1, self.settings.max_parallel_audio_jobs + self.settings.max_parallel_video_jobs)
        self.workers = [asyncio.create_task(self._worker()) for _ in range(worker_count)]
        logger.info("Job manager started with %s queued jobs", len(rows))

    async def stop(self) -> None:
        self._stopped.set()
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    async def create_job(self, telegram_id: int, job_type: str, **fields: Any) -> int:
        now = now_iso()
        allowed = {
            "parent_job_id",
            "source_audio_job_id",
            "voice_id",
            "voice_name",
            "text",
            "image_file_id",
            "audio_file_id",
            "source_image_file_id",
            "hedra_audio_asset_id",
            "hedra_image_asset_id",
        }
        columns = ["telegram_id", "job_type", "status", "expires_at", "created_at", "updated_at"]
        values: list[Any] = [telegram_id, job_type, JobStatus.QUEUED.value, iso_after_hours(self.settings.tmp_file_ttl_hours), now, now]
        for key in allowed:
            if key in fields:
                columns.append(key)
                values.append(fields[key])
        placeholders = ", ".join("?" for _ in columns)
        cur = await self.db.execute(
            f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        job_id = int(cur.lastrowid)
        await self.enqueue(job_id)
        return job_id

    async def enqueue(self, job_id: int) -> None:
        await self.queue.put(job_id)

    async def cancel_job(self, job_id: int) -> bool:
        row = await self.db.fetchone("SELECT status FROM jobs WHERE id=?", (job_id,))
        if not row:
            return False
        if row["status"] == JobStatus.COMPLETE.value:
            return False
        await self._update_job(job_id, status=JobStatus.CANCELLED.value, error_message="Задача отменена администратором.")
        return True

    async def repeat_audio(self, source_job_id: int, telegram_id: int) -> int | None:
        row = await self.db.fetchone("SELECT * FROM jobs WHERE id=? AND job_type='tts'", (source_job_id,))
        if not row:
            return None
        return await self.create_job(
            telegram_id=telegram_id,
            job_type=JobType.TTS.value,
            text=row["text"],
            voice_id=row["voice_id"],
            voice_name=row["voice_name"],
        )

    async def delete_local_result(self, job_id: int, telegram_id: int, admin: bool) -> bool:
        row = await self.db.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row or (not admin and row["telegram_id"] != telegram_id):
            return False
        path_value = row["local_result_path"]
        if path_value:
            path = Path(path_value)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Failed to delete result %s", path)
        await self._update_job(job_id, local_result_path=None)
        return True

    async def _worker(self) -> None:
        while not self._stopped.is_set():
            job_id = await self.queue.get()
            try:
                row = await self.db.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
                if not row or row["status"] != JobStatus.QUEUED.value:
                    continue
                job_type = row["job_type"]
                if job_type in AUDIO_JOB_TYPES:
                    async with self.audio_sem:
                        await self._process(dict(row))
                elif job_type in VIDEO_JOB_TYPES:
                    async with self.video_sem:
                        await self._process(dict(row))
                else:
                    await self._fail(job_id, f"Неизвестный тип задачи: {job_type}")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker failed for job %s", job_id)
                await self._fail(job_id, "Внутренняя ошибка обработки задачи.")
            finally:
                self.queue.task_done()

    async def _process(self, job: dict[str, Any]) -> None:
        status = await self.db.fetchone("SELECT status FROM jobs WHERE id=?", (job["id"],))
        if status and status["status"] == JobStatus.CANCELLED.value:
            return
        if job["job_type"] == JobType.TTS.value:
            await self._process_tts(job)
        elif job["job_type"] == JobType.VIDEO_FROM_TEXT.value:
            await self._process_video_from_text(job)
        elif job["job_type"] == JobType.VIDEO_FROM_UPLOADED_AUDIO.value:
            await self._process_video_from_uploaded_audio(job)
        elif job["job_type"] == JobType.VIDEO_FROM_GENERATED_AUDIO.value:
            await self._process_video_from_generated_audio(job)

    async def _process_tts(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await self.bot.send_message(job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            generation = await self.tts.generate(job["voice_id"], job["text"])
            generation_id = extract_id(generation)
            if not generation_id:
                raise RuntimeError("Hedra не вернула generation id.")
            await self._update_job(job_id, status=JobStatus.SUBMITTED.value, hedra_generation_id=generation_id)
            status = await self._poll_generation(job_id, generation_id, job["telegram_id"])
            url = extract_download_url(status)
            if not url:
                raise RuntimeError("Hedra не вернула ссылку на аудио.")
            await self._update_job(job_id, status=JobStatus.DOWNLOADING.value)
            result_path = self.settings.tmp_dir / f"job_{job_id}_audio.mp3"
            await self.hedra.download_file(url, result_path)
            await self._update_job(
                job_id,
                status=JobStatus.COMPLETE.value,
                result_download_url=url,
                result_streaming_url=extract_streaming_url(status),
                result_url=url,
                hedra_audio_asset_id=extract_audio_asset_id(status),
                local_result_path=str(result_path),
                completed_at=now_iso(),
            )
            await self.bot.send_audio(
                job["telegram_id"],
                FSInputFile(result_path),
                caption=f"Задача #{job_id} готова.",
                reply_markup=audio_result_keyboard(job_id),
            )
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_video_from_text(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await self._ensure_video_can_start()
            model_id = await self._video_model_or_fail()
            await self.bot.send_message(job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            await self._update_job(job_id, status=JobStatus.UPLOADING_ASSETS.value)
            image_path = await self.files.download_image_file_id(job["image_file_id"], job_id)
            image_asset_id = await self._upload_asset(job_id, image_path, "image", f"telegram_image_{job_id}{image_path.suffix}")
            await self._update_job(job_id, hedra_image_asset_id=image_asset_id)
            generation = await self.video.with_inline_tts(image_asset_id, job["voice_id"], job["text"], model_id)
            await self._finish_video_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_video_from_uploaded_audio(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await self._ensure_video_can_start()
            model_id = await self._video_model_or_fail()
            await self.bot.send_message(job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            await self._update_job(job_id, status=JobStatus.UPLOADING_ASSETS.value)
            image_path = await self.files.download_image_file_id(job["image_file_id"], job_id)
            audio_path = await self.files.download_audio_file_id(job["audio_file_id"], job_id)
            image_asset_id = await self._upload_asset(job_id, image_path, "image", f"telegram_image_{job_id}{image_path.suffix}")
            audio_asset_id = await self._upload_asset(job_id, audio_path, "audio", f"telegram_audio_{job_id}{audio_path.suffix}")
            await self._update_job(job_id, hedra_image_asset_id=image_asset_id, hedra_audio_asset_id=audio_asset_id)
            generation = await self.video.with_audio(image_asset_id, audio_asset_id, model_id)
            await self._finish_video_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_video_from_generated_audio(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await self._ensure_video_can_start()
            model_id = await self._video_model_or_fail()
            source = await self.db.fetchone("SELECT * FROM jobs WHERE id=?", (job["source_audio_job_id"],))
            if not source or source["status"] != JobStatus.COMPLETE.value:
                raise RuntimeError("Исходная аудио-задача недоступна.")
            await self.bot.send_message(job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            await self._update_job(job_id, status=JobStatus.UPLOADING_ASSETS.value)
            image_path = await self.files.download_image_file_id(job["source_image_file_id"], job_id)
            image_asset_id = await self._upload_asset(job_id, image_path, "image", f"telegram_image_{job_id}{image_path.suffix}")
            audio_asset_id = source["hedra_audio_asset_id"]
            if not audio_asset_id:
                audio_path = await self._source_audio_path(dict(source), job_id)
                audio_asset_id = await self._upload_asset(job_id, audio_path, "audio", f"generated_audio_{source['id']}{audio_path.suffix}")
                await self.db.execute(
                    "UPDATE jobs SET hedra_audio_asset_id=?, updated_at=? WHERE id=?",
                    (audio_asset_id, now_iso(), source["id"]),
                )
            await self._update_job(job_id, hedra_image_asset_id=image_asset_id, hedra_audio_asset_id=audio_asset_id)
            generation = await self.video.with_audio(image_asset_id, audio_asset_id, model_id)
            await self._finish_video_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _finish_video_generation(self, job: dict[str, Any], generation: dict[str, Any]) -> None:
        job_id = job["id"]
        generation_id = extract_id(generation)
        if not generation_id:
            raise RuntimeError("Hedra не вернула generation id.")
        await self._update_job(job_id, status=JobStatus.SUBMITTED.value, hedra_generation_id=generation_id)
        status = await self._poll_generation(job_id, generation_id, job["telegram_id"])
        url = extract_download_url(status)
        if not url:
            raise RuntimeError("Hedra не вернула ссылку на видео.")
        await self._update_job(job_id, status=JobStatus.DOWNLOADING.value)
        result_path = self.settings.tmp_dir / f"job_{job_id}_video.mp4"
        await self.hedra.download_file(url, result_path)
        await self._update_job(
            job_id,
            status=JobStatus.COMPLETE.value,
            result_download_url=url,
            result_streaming_url=extract_streaming_url(status),
            result_url=url,
            local_result_path=str(result_path),
            completed_at=now_iso(),
        )
        caption = f"Задача #{job_id} готова."
        if job.get("source_audio_job_id"):
            caption += f"\nСоздано из аудио-задачи #{job['source_audio_job_id']}."
        await self.bot.send_video(job["telegram_id"], FSInputFile(result_path), caption=caption)

    async def _poll_generation(self, job_id: int, generation_id: str, telegram_id: int) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.settings.job_timeout_sec
        last_notice = 0.0
        last: dict[str, Any] = {}
        await self._update_job(job_id, status=JobStatus.PROCESSING.value)
        while asyncio.get_running_loop().time() < deadline:
            row = await self.db.fetchone("SELECT status FROM jobs WHERE id=?", (job_id,))
            if row and row["status"] == JobStatus.CANCELLED.value:
                raise RuntimeError("Задача отменена.")
            last = await self.hedra.get_generation_status(generation_id)
            status = str(last.get("status") or last.get("state") or "").lower()
            if status in {"complete", "completed", "succeeded", "success", "done"}:
                return last
            if status in {"error", "failed", "failure", "cancelled"}:
                raise RuntimeError(str(last.get("error") or last.get("message") or "Hedra вернула ошибку генерации."))
            now = asyncio.get_running_loop().time()
            if now - last_notice >= 30:
                last_notice = now
                progress = last.get("progress")
                suffix = f" Прогресс: {progress}%." if progress is not None else ""
                await self.bot.send_message(telegram_id, f"Задача #{job_id} обрабатывается.{suffix}")
            await asyncio.sleep(self.settings.job_poll_interval_sec)
        raise TimeoutError("Генерация не успела завершиться за лимит времени.")

    async def _upload_asset(self, job_id: int, path: Path, asset_type: str, name: str) -> str:
        asset = await self.hedra.create_asset(name, asset_type)
        asset_id = extract_id(asset)
        if not asset_id:
            raise RuntimeError(f"Hedra не вернула asset id для {asset_type}.")
        await self.hedra.upload_asset(asset_id, path)
        await self._update_job(job_id, hedra_asset_id=asset_id)
        return asset_id

    async def _source_audio_path(self, source: dict[str, Any], job_id: int) -> Path:
        local = source.get("local_result_path")
        if local and Path(local).exists():
            return Path(local)
        url = source.get("result_download_url") or source.get("result_streaming_url")
        if not url:
            raise RuntimeError("Аудиофайл уже очищен. Сгенерируй аудио заново.")
        path = self.settings.tmp_dir / f"job_{job_id}_source_audio.mp3"
        try:
            await self.hedra.download_file(url, path)
            return path
        except HedraApiError as exc:
            raise RuntimeError("Аудиофайл уже очищен. Сгенерируй аудио заново.") from exc

    async def _ensure_video_can_start(self) -> None:
        ok, message = await self.credits_service.ensure_video_credits()
        if not ok:
            raise RuntimeError(message or "Недостаточно credits для генерации видео.")

    async def _video_model_or_fail(self) -> str:
        model_id = await self.model_service.choose_default_avatar_model()
        if not model_id:
            raise RuntimeError("Не найдена Hedra video model с поддержкой 1:1. Выполни /admin_models_sync и /admin_set_video_model.")
        return model_id

    async def _mark_interrupted_jobs(self) -> None:
        await self.db.execute(
            """
            UPDATE jobs
            SET status='interrupted',
                error_message='Бот был перезапущен во время обработки. Запусти задачу заново.',
                updated_at=?
            WHERE status IN ('submitted', 'processing', 'downloading', 'uploading_assets')
            """,
            (now_iso(),),
        )

    async def _timeout(self, job_id: int, telegram_id: int) -> None:
        message = "Генерация не успела завершиться за лимит времени."
        await self._update_job(job_id, status=JobStatus.TIMEOUT.value, error_message=message, completed_at=now_iso())
        await self.bot.send_message(telegram_id, f"Задача #{job_id}: {message}")

    async def _fail(self, job_id: int, message: str, telegram_id: int | None = None) -> None:
        await self._update_job(job_id, status=JobStatus.ERROR.value, error_message=short_error(message), completed_at=now_iso())
        row = await self.db.fetchone("SELECT telegram_id FROM jobs WHERE id=?", (job_id,))
        target = telegram_id or (row["telegram_id"] if row else None)
        if target:
            await self.bot.send_message(target, f"Задача #{job_id} завершилась ошибкой: {short_error(message)}")
        if "Не найдена Hedra video model" in message and target != self.settings.admin_telegram_id:
            await self.bot.send_message(self.settings.admin_telegram_id, f"Задача #{job_id}: {short_error(message)}")

    async def _update_job(self, job_id: int, **fields: Any) -> None:
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{key}=?" for key in fields)
        await self.db.execute(
            f"UPDATE jobs SET {assignments} WHERE id=?",
            [*fields.values(), job_id],
        )


def extract_download_url(data: dict[str, Any]) -> str | None:
    for key in ("download_url", "result_download_url", "url", "result_url"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("asset", "result", "data", "output", "video", "audio"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_download_url(nested)
            if found:
                return found
    return None


def extract_streaming_url(data: dict[str, Any]) -> str | None:
    for key in ("streaming_url", "result_streaming_url", "stream_url"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("asset", "result", "data", "output", "video", "audio"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_streaming_url(nested)
            if found:
                return found
    return None


def extract_audio_asset_id(data: dict[str, Any]) -> str | None:
    for key in ("audio_id", "audio_asset_id", "asset_id"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("asset", "result", "data", "output", "audio"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_audio_asset_id(nested)
            if found:
                return found
    return None


def humanize_exception(exc: Exception) -> str:
    if isinstance(exc, HedraApiError):
        return str(exc)
    message = str(exc).strip()
    return message or "Неизвестная ошибка."
