from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import Settings
from app.db import Database
from app.files import FilesService
from app.hedra_client import HedraApiError, HedraClient, extract_asset_url
from app.keyboards import audio_result_keyboard
from app.models import AUDIO_JOB_TYPES, VIDEO_JOB_TYPES, JobStatus, JobType
from app.services.credits_service import CreditsService
from app.services.model_adapters import ModelAdapterError, fallback_image_url_payloads, get_adapter_for_model
from app.services.model_service import ModelService, supports_image_edit
from app.services.tts_service import TtsService
from app.services.video_service import VideoService
from app.services.voice_clone_service import extract_id
from app.ui_messages import send_tracked_message
from app.utils import iso_after_hours, now_iso, short_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadedAsset:
    id: str
    url: str | None
    raw_create: dict[str, Any]
    raw_upload: dict[str, Any]


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
            "text_prompt",
            "prompt_mode",
            "duration_ms",
            "selected_model_id",
            "selected_model_name",
            "generation_family",
            "input_image_asset_id",
            "input_image_url",
            "input_image_source",
            "input_image_sha256",
            "adapter_name",
            "request_payload_keys",
            "hedra_error_raw",
            "hedra_upload_raw",
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
        elif job["job_type"] == JobType.IMAGE_TO_VIDEO.value:
            await self._process_image_to_video(job)
        elif job["job_type"] == JobType.TEXT_TO_IMAGE.value:
            await self._process_text_to_image(job)
        elif job["job_type"] == JobType.IMAGE_EDIT.value:
            await self._process_image_edit(job)

    async def _process_tts(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await send_tracked_message(self.bot, job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
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
            model_id = job.get("selected_model_id") or await self._video_model_or_fail()
            await send_tracked_message(self.bot, job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            await self._update_job(job_id, status=JobStatus.UPLOADING_ASSETS.value)
            image_path = await self.files.download_image_file_id(job["image_file_id"], job_id)
            image_asset_id = await self._upload_asset(job_id, image_path, "image", f"telegram_image_{job_id}{image_path.suffix}")
            await self._update_job(job_id, hedra_image_asset_id=image_asset_id)
            generation = await self.video.with_inline_tts(image_asset_id, job["voice_id"], job["text"], model_id, job.get("text_prompt"))
            await self._finish_video_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_video_from_uploaded_audio(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await self._ensure_video_can_start()
            model_id = job.get("selected_model_id") or await self._video_model_or_fail()
            await send_tracked_message(self.bot, job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            await self._update_job(job_id, status=JobStatus.UPLOADING_ASSETS.value)
            image_path = await self.files.download_image_file_id(job["image_file_id"], job_id)
            audio_path = await self.files.download_audio_file_id(job["audio_file_id"], job_id)
            image_asset_id = await self._upload_asset(job_id, image_path, "image", f"telegram_image_{job_id}{image_path.suffix}")
            audio_asset_id = await self._upload_asset(job_id, audio_path, "audio", f"telegram_audio_{job_id}{audio_path.suffix}")
            await self._update_job(job_id, hedra_image_asset_id=image_asset_id, hedra_audio_asset_id=audio_asset_id)
            generation = await self.video.with_audio(image_asset_id, audio_asset_id, model_id, job.get("text_prompt"))
            await self._finish_video_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_video_from_generated_audio(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await self._ensure_video_can_start()
            model_id = job.get("selected_model_id") or await self._video_model_or_fail()
            source = await self.db.fetchone("SELECT * FROM jobs WHERE id=?", (job["source_audio_job_id"],))
            if not source or source["status"] != JobStatus.COMPLETE.value:
                raise RuntimeError("Исходная аудио-задача недоступна.")
            await send_tracked_message(self.bot, job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
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
            generation = await self.video.with_audio(image_asset_id, audio_asset_id, model_id, job.get("text_prompt"))
            await self._finish_video_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_image_to_video(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            await self._ensure_video_can_start()
            model_id = job.get("selected_model_id") or await self._video_model_or_fail()
            model = await self.db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
            if model and model["requires_audio_input"]:
                raise RuntimeError("Эта модель требует аудио. Выбери другую video model для Фото → видео.")
            await send_tracked_message(self.bot, job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            await self._update_job(job_id, status=JobStatus.UPLOADING_ASSETS.value)
            image_path = await self.files.download_image_file_id(job["image_file_id"], job_id)
            image_asset_id = await self._upload_asset(job_id, image_path, "image", f"image_to_video_{job_id}{image_path.suffix}")
            await self._update_job(job_id, hedra_image_asset_id=image_asset_id)
            prompt = job.get("text_prompt")
            duration_ms = int(job.get("duration_ms") or self.settings.default_video_duration_ms)
            try:
                generation = await self.hedra.generate_video_from_image(
                    image_asset_id=image_asset_id,
                    text_prompt=prompt,
                    model_id=model_id,
                    aspect_ratio=self.settings.default_video_aspect_ratio,
                    resolution=self.settings.default_video_resolution,
                    duration_ms=duration_ms,
                )
            except HedraApiError as exc:
                allowed = extract_allowed_duration_values(str(exc))
                if _is_duration_error(str(exc)):
                    duration_ms = normalize_duration_ms(duration_ms, allowed or None)
                    await self.model_service.mark_duration_required(model_id, allowed or None, duration_ms)
                    await self._update_job(job_id, duration_ms=duration_ms, hedra_error_raw=_error_raw(exc))
                    await send_tracked_message(
                        self.bot,
                        job["telegram_id"],
                        f"Задача #{job_id}: модель требует длительность видео. Исправляю на {duration_ms} ms и повторяю.",
                    )
                    generation = await self.hedra.generate_video_from_image(
                        image_asset_id=image_asset_id,
                        text_prompt=prompt,
                        model_id=model_id,
                        aspect_ratio=self.settings.default_video_aspect_ratio,
                        resolution=self.settings.default_video_resolution,
                        duration_ms=duration_ms,
                    )
                elif not job.get("text_prompt"):
                    logger.info("Retry image_to_video with fallback prompt after Hedra error: %s", exc)
                    prompt = self.settings.default_video_no_audio_prompt
                    await self._update_job(job_id, text_prompt=prompt, prompt_mode="fallback_default", hedra_error_raw=_error_raw(exc))
                    generation = await self.hedra.generate_video_from_image(
                        image_asset_id=image_asset_id,
                        text_prompt=prompt,
                        model_id=model_id,
                        aspect_ratio=self.settings.default_video_aspect_ratio,
                        resolution=self.settings.default_video_resolution,
                        duration_ms=duration_ms,
                    )
                else:
                    await self._update_job(job_id, hedra_error_raw=_error_raw(exc))
                    raise
            await self._update_job(job_id, duration_ms=duration_ms)
            await self._finish_video_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_text_to_image(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            model_id = job.get("selected_model_id") or await self._image_model_or_fail()
            prompt = job.get("text_prompt")
            if not prompt:
                raise RuntimeError("Prompt для изображения пустой.")
            await send_tracked_message(self.bot, job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            generation = await self.hedra.generate_image(
                text_prompt=prompt,
                model_id=model_id,
                aspect_ratio=self.settings.default_image_aspect_ratio,
                resolution=self.settings.default_image_resolution,
            )
            await self._finish_image_generation(job, generation)
        except TimeoutError:
            await self._timeout(job_id, job["telegram_id"])
        except Exception as exc:
            await self._fail(job_id, humanize_exception(exc), job["telegram_id"])

    async def _process_image_edit(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            model_id = job.get("selected_model_id") or await self._image_model_or_fail()
            model = await self.db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
            if not model or not supports_image_edit(dict(model)):
                raise RuntimeError(
                    "Редактирование изображений доступно в Hedra web-интерфейсе, но текущий API не отдаёт "
                    "совместимый image-edit режим для выбранной модели."
                )
            prompt = job.get("text_prompt")
            if not prompt:
                raise RuntimeError("Prompt редактирования пустой.")
            await send_tracked_message(self.bot, job["telegram_id"], f"Задача #{job_id} отправлена в Hedra.")
            await self._update_job(job_id, status=JobStatus.UPLOADING_ASSETS.value)
            image_path = await self.files.download_image_file_id(job["image_file_id"], job_id)
            image_sha256 = file_sha256(image_path)
            uploaded = await self._upload_asset_full(job_id, image_path, "image", f"image_edit_{job_id}{image_path.suffix}")
            image_asset_id = uploaded.id
            image_url = uploaded.url
            image_source = "upload_response.asset.url" if image_url else "missing"
            if not image_url:
                image_url = await self.hedra.try_get_asset_url(image_asset_id)
                image_source = "exact_asset_lookup" if image_url else "missing"
            await self._update_job(
                job_id,
                input_image_asset_id=image_asset_id,
                input_image_url=image_url,
                input_image_source=image_source,
                input_image_sha256=image_sha256,
            )
            adapter = get_adapter_for_model(model["raw_json"], "image_edit", model["name"])
            try:
                prepared = await adapter.build(
                    hedra_client=self.hedra,
                    image_asset_id=image_asset_id,
                    image_url=image_url,
                    local_image_path=image_path,
                    model_id=model_id,
                    text_prompt=prompt,
                    aspect_ratio=self.settings.default_image_aspect_ratio,
                    resolution=self.settings.default_image_resolution,
                )
            except ModelAdapterError as exc:
                await self._update_job(
                    job_id,
                    input_image_asset_id=image_asset_id,
                    adapter_name=adapter.name,
                    request_payload_keys="",
                    hedra_error_raw=str(exc),
                )
                raise
            if prepared.input_image_url and prepared.input_image_url != image_url:
                if prepared.input_image_url.startswith("data:"):
                    image_source = "data_uri_current_file"
                    await self._update_job(job_id, input_image_source=image_source)
                else:
                    logger.error(
                        "Image edit adapter attempted to use non-current image URL job_id=%s asset_id=%s prepared_url=%s job_url=%s",
                        job_id,
                        image_asset_id,
                        _safe_url_for_log(prepared.input_image_url),
                        _safe_url_for_log(image_url),
                    )
                    raise RuntimeError("Внутренняя защита: adapter попытался использовать image URL не из текущей задачи.")
            if prepared.input_image_asset_id and prepared.input_image_asset_id != image_asset_id:
                raise RuntimeError("Внутренняя защита: adapter попытался использовать image asset не из текущей задачи.")
            effective_input_image_url = prepared.input_image_url or image_url
            stored_input_image_url = (
                None
                if effective_input_image_url and effective_input_image_url.startswith("data:")
                else effective_input_image_url
            )
            await self._update_job(
                job_id,
                input_image_asset_id=image_asset_id,
                input_image_url=stored_input_image_url,
                input_image_source=prepared.input_image_source or image_source,
                adapter_name=prepared.adapter_name,
                request_payload_keys=json.dumps(prepared.payload_keys, ensure_ascii=False),
            )
            try:
                generation = await self.hedra.generate_image_edit(prepared.payload)
            except HedraApiError as exc:
                if _is_missing_image_url_error(str(exc)):
                    fallback_url = prepared.input_image_url or image_url or self.hedra.build_data_uri(image_path)
                    if fallback_url.startswith("data:"):
                        await self._update_job(job_id, input_image_source="data_uri_current_file")
                    generation = await self._retry_grok_i2i_with_url_fields(job_id, prepared.payload, fallback_url, dict(model))
                else:
                    logger.warning(
                        "Image edit failed model_id=%s model_name=%s generation_family=image_edit adapter=%s keys=%s asset_id=%s status=%s error=%s",
                        model_id,
                        model["name"],
                        prepared.adapter_name,
                        prepared.payload_keys,
                        image_asset_id,
                        exc.status,
                        exc,
                    )
                    await self._update_job(job_id, hedra_error_raw=_error_raw(exc))
                    raise
            await self._finish_image_generation(job, generation)
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

    async def _finish_image_generation(self, job: dict[str, Any], generation: dict[str, Any]) -> None:
        job_id = job["id"]
        generation_id = extract_id(generation)
        if not generation_id:
            raise RuntimeError("Hedra не вернула generation id.")
        await self._update_job(job_id, status=JobStatus.SUBMITTED.value, hedra_generation_id=generation_id)
        status = await self._poll_generation(job_id, generation_id, job["telegram_id"])
        url, status = await self._resolve_generation_result_url(job_id, generation_id, status, "image")
        if not url:
            raw = compact_error_payload(status)
            await self._update_job(job_id, hedra_error_raw=raw)
            logger.warning("Hedra image generation completed without URL job_id=%s generation_id=%s status=%s", job_id, generation_id, raw)
            raise RuntimeError("Hedra завершила генерацию, но не вернула ссылку на изображение. Администратор может посмотреть status JSON через /admin_job.")
        await self._update_job(job_id, status=JobStatus.DOWNLOADING.value)
        result_path = self.settings.tmp_dir / f"job_{job_id}_image.png"
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
        await self.bot.send_photo(job["telegram_id"], FSInputFile(result_path), caption=f"Задача #{job_id} готова.")

    async def _resolve_generation_result_url(
        self,
        job_id: int,
        generation_id: str,
        initial_status: dict[str, Any],
        asset_type: str,
    ) -> tuple[str | None, dict[str, Any]]:
        status = initial_status
        for attempt in range(6):
            url = extract_download_url(status)
            if url:
                return url, status
            asset_id = extract_result_asset_id(status, asset_type)
            if asset_id:
                asset_url = await self.hedra.try_get_asset_url(asset_id)
                if asset_url:
                    if asset_type == "image":
                        await self._update_job(job_id, hedra_image_asset_id=asset_id)
                    elif asset_type == "audio":
                        await self._update_job(job_id, hedra_audio_asset_id=asset_id)
                    return asset_url, status
            if attempt < 5:
                await asyncio.sleep(min(self.settings.job_poll_interval_sec, 5))
                status = await self.hedra.get_generation_status(generation_id)
                current = str(status.get("status") or status.get("state") or "").lower()
                if current in {"error", "failed", "failure", "cancelled"}:
                    raise RuntimeError(str(status.get("error_message") or status.get("error") or status.get("message") or "Hedra вернула ошибку генерации."))
        return None, status

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
            if status in {"complete", "completed"}:
                return last
            if status in {"error", "failed", "failure", "cancelled"}:
                raise RuntimeError(str(last.get("error_message") or last.get("error") or last.get("message") or "Hedra вернула ошибку генерации."))
            now = asyncio.get_running_loop().time()
            if now - last_notice >= 30:
                last_notice = now
                progress = last.get("progress")
                suffix = f" Прогресс: {progress}%." if progress is not None else ""
                await send_tracked_message(self.bot, telegram_id, f"Задача #{job_id} обрабатывается.{suffix}")
            await asyncio.sleep(self.settings.job_poll_interval_sec)
        raise TimeoutError("Генерация не успела завершиться за лимит времени.")

    async def _upload_asset(self, job_id: int, path: Path, asset_type: str, name: str) -> str:
        return (await self._upload_asset_full(job_id, path, asset_type, name)).id

    async def _upload_asset_full(self, job_id: int, path: Path, asset_type: str, name: str) -> UploadedAsset:
        asset = await self.hedra.create_asset(name, asset_type)
        asset_id = extract_id(asset)
        if not asset_id:
            raise RuntimeError(f"Hedra не вернула asset id для {asset_type}.")
        upload = await self.hedra.upload_asset(asset_id, path)
        asset_url = extract_asset_url(upload)
        fields: dict[str, Any] = {
            "hedra_asset_id": asset_id,
            "hedra_upload_raw": compact_error_payload(upload),
        }
        if asset_type == "image":
            fields.update(
                {
                    "hedra_image_asset_id": asset_id,
                    "input_image_asset_id": asset_id,
                    "input_image_url": asset_url,
                }
            )
        elif asset_type == "audio":
            fields["hedra_audio_asset_id"] = asset_id
        await self._update_job(job_id, **fields)
        return UploadedAsset(asset_id, asset_url, asset, upload)

    async def _retry_grok_i2i_with_url_fields(
        self,
        job_id: int,
        base_payload: dict[str, Any],
        image_url: str,
        model: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: HedraApiError | None = None
        for extra in fallback_image_url_payloads(image_url):
            payload = dict(base_payload)
            for key in ("image_url", "image_urls", "images", "image", "reference_image_urls", "source_image_url", "input_image_url"):
                payload.pop(key, None)
            payload.update(extra)
            await self._update_job(job_id, request_payload_keys=json.dumps(list(payload.keys()), ensure_ascii=False))
            try:
                return await self.hedra.generate_image_edit(payload)
            except HedraApiError as exc:
                last_error = exc
                logger.warning(
                    "Grok I2I fallback failed model_id=%s model_name=%s keys=%s status=%s error=%s",
                    model.get("id"),
                    model.get("name"),
                    list(payload.keys()),
                    exc.status,
                    exc,
                )
        if last_error:
            await self._update_job(job_id, hedra_error_raw=_error_raw(last_error))
            raise last_error
        raise RuntimeError("Не удалось подобрать payload для Grok Imagine I2I.")

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

    async def _image_model_or_fail(self) -> str:
        model_id = await self.model_service.choose_default_image_model()
        if not model_id:
            raise RuntimeError("Не найдена Hedra image model. Выполни /admin_models_sync и выбери image model.")
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
        await send_tracked_message(self.bot, telegram_id, f"Задача #{job_id}: {message}")

    async def _fail(self, job_id: int, message: str, telegram_id: int | None = None) -> None:
        user_message = humanize_user_error(message)
        update_fields: dict[str, Any] = {
            "status": JobStatus.ERROR.value,
            "error_message": short_error(user_message),
            "completed_at": now_iso(),
        }
        if "hedra" in message.lower() or "422" in message or "UNKNOWN" in message:
            update_fields["hedra_error_raw"] = message[:4000]
        await self._update_job(job_id, **update_fields)
        row = await self.db.fetchone("SELECT telegram_id FROM jobs WHERE id=?", (job_id,))
        target = telegram_id or (row["telegram_id"] if row else None)
        if target:
            await send_tracked_message(self.bot, target, f"Задача #{job_id} завершилась ошибкой: {short_error(user_message)}")
        if "Не найдена Hedra video model" in message and target != self.settings.admin_telegram_id:
            await send_tracked_message(self.bot, self.settings.admin_telegram_id, f"Задача #{job_id}: {short_error(message)}")

    async def _update_job(self, job_id: int, **fields: Any) -> None:
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{key}=?" for key in fields)
        await self.db.execute(
            f"UPDATE jobs SET {assignments} WHERE id=?",
            [*fields.values(), job_id],
        )


def extract_download_url(data: dict[str, Any]) -> str | None:
    for key in ("download_url", "url", "result_download_url", "result_url"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("asset", "result", "data", "output", "video", "audio", "image", "batch_results", "results", "assets", "outputs"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_download_url(nested)
            if found:
                return found
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    found = extract_download_url(item)
                    if found:
                        return found
    return None


def extract_streaming_url(data: dict[str, Any]) -> str | None:
    for key in ("streaming_url", "result_streaming_url", "stream_url"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("asset", "result", "data", "output", "video", "audio", "image", "batch_results", "results", "assets", "outputs"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_streaming_url(nested)
            if found:
                return found
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    found = extract_streaming_url(item)
                    if found:
                        return found
    return None


def extract_audio_asset_id(data: dict[str, Any]) -> str | None:
    for key in ("audio_id", "audio_asset_id", "asset_id"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("asset", "result", "data", "output", "audio", "batch_results", "results", "assets", "outputs"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_audio_asset_id(nested)
            if found:
                return found
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    found = extract_audio_asset_id(item)
                    if found:
                        return found
    return None


def extract_result_asset_id(data: dict[str, Any], asset_type: str | None = None) -> str | None:
    preferred_keys = (
        "asset_id",
        "result_asset_id",
        "image_asset_id",
        "image_id",
        "audio_asset_id",
        "audio_id",
        "id",
    )
    for key in preferred_keys:
        value = data.get(key)
        if value and (key != "id" or _looks_like_asset_container(data, asset_type)):
            return str(value)
    for key in ("asset", "result", "data", "output", "image", "audio", "video", "batch_results", "results", "assets", "outputs"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_result_asset_id(nested, asset_type)
            if found:
                return found
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    found = extract_result_asset_id(item, asset_type)
                    if found:
                        return found
    return None


def _looks_like_asset_container(data: dict[str, Any], asset_type: str | None) -> bool:
    if not asset_type:
        return True
    text = " ".join(str(data.get(key) or "") for key in ("type", "asset_type", "mime_type", "content_type", "name")).lower()
    return asset_type in text or not text


def extract_allowed_duration_values(error_text: str) -> list[int]:
    match = re.search(r"Valid values:\s*\[([^\]]+)\]", error_text, flags=re.IGNORECASE)
    source = match.group(1) if match else error_text
    values = sorted({int(value) for value in re.findall(r"\b\d{4,6}\b", source)})
    return [value for value in values if 1000 <= value <= 120000]


def normalize_duration_ms(requested: int, allowed_values: list[int] | None) -> int:
    if allowed_values:
        return min(allowed_values, key=lambda value: (abs(value - requested), value))
    return 5000


def _is_duration_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return "duration_ms" in lowered and ("required" in lowered or "valid values" in lowered)


def _is_missing_image_url_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return "image url" in lowered and ("required" in lowered or "at least one" in lowered)


def _error_raw(exc: Exception) -> str:
    if isinstance(exc, HedraApiError) and exc.payload is not None:
        return compact_error_payload(exc.payload)
    return str(exc)


def compact_error_payload(payload: Any) -> str:
    try:
        return json.dumps(_redact_binary(payload), ensure_ascii=False)[:4000]
    except TypeError:
        return str(payload)[:4000]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_url_for_log(url: str | None) -> str:
    if not url:
        return "-"
    if url.startswith("data:"):
        return "data-uri"
    return url if len(url) <= 80 else f"{url[:35]}...{url[-12:]}"


def _redact_binary(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: _redact_binary(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_redact_binary(item) for item in data]
    if isinstance(data, str) and data.startswith("data:") and "base64," in data[:100]:
        return data[:40] + "...[base64 redacted]"
    return data


def humanize_exception(exc: Exception) -> str:
    if isinstance(exc, HedraApiError):
        return str(exc)
    message = str(exc).strip()
    return message or "Неизвестная ошибка."


def humanize_user_error(message: str) -> str:
    lowered = message.lower()
    if "duration_ms" in lowered and ("required" in lowered or "valid values" in lowered):
        return "Модель требует duration_ms. Выбери длительность видео в настройках и повтори задачу."
    if "image url" in lowered and "required" in lowered or "at least one image url" in lowered:
        return "Эта image model требует image URL/reference image, но текущий Hedra API не дал совместимый способ передать загруженное изображение. Попробуй другую image model."
    if "http 422" in lowered or "'type': 'unknown'" in lowered or '"code":422' in lowered:
        return "Hedra отклонила параметры модели. Администратор может посмотреть техническую ошибку через /admin_job."
    return message
