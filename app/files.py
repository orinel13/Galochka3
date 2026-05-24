from __future__ import annotations

import asyncio
import mimetypes
import shutil
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.types import Document, Message, PhotoSize

from app.config import Settings
from app.utils import sanitize_filename_part


IMAGE_MIME = {"image/jpeg", "image/png"}
AUDIO_MIME = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg", "audio/mp3"}


class FileValidationError(RuntimeError):
    pass


class FilesService:
    def __init__(self, settings: Settings, bot: Bot) -> None:
        self.settings = settings
        self.bot = bot

    def tmp_path(self, job_id: int, suffix: str) -> Path:
        safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return self.settings.tmp_dir / f"job_{job_id}_{stamp}{safe_suffix}"

    async def download_photo(self, message: Message, job_id: int) -> tuple[Path, str]:
        file_id: str | None = None
        suffix = ".jpg"
        if message.photo:
            largest: PhotoSize = message.photo[-1]
            file_id = largest.file_id
            size = largest.file_size or 0
            if size and size > self.settings.max_image_file_bytes:
                raise FileValidationError("Файл слишком большой.")
        elif message.document:
            self._validate_document_image(message.document)
            file_id = message.document.file_id
            suffix = mimetypes.guess_extension(message.document.mime_type or "") or ".jpg"
        if not file_id:
            raise FileValidationError("Пришли фото JPG или PNG.")
        path = self.tmp_path(job_id, suffix)
        await self.bot.download(file_id, destination=path)
        self._check_size(path, self.settings.max_image_file_bytes)
        return path, file_id

    async def download_audio(self, message: Message, job_id: int, convert_voice: bool = True) -> tuple[Path, str]:
        file_id: str | None = None
        suffix = ".mp3"
        if message.voice:
            file_id = message.voice.file_id
            suffix = ".ogg"
            if message.voice.file_size and message.voice.file_size > self.settings.max_audio_file_bytes:
                raise FileValidationError("Файл слишком большой.")
        elif message.audio:
            file_id = message.audio.file_id
            suffix = _suffix_from_name_or_mime(message.audio.file_name, message.audio.mime_type, ".mp3")
            if message.audio.file_size and message.audio.file_size > self.settings.max_audio_file_bytes:
                raise FileValidationError("Файл слишком большой.")
        elif message.document:
            self._validate_document_audio(message.document)
            file_id = message.document.file_id
            suffix = _suffix_from_name_or_mime(message.document.file_name, message.document.mime_type, ".mp3")
        if not file_id:
            raise FileValidationError("Пришли аудио, voice или audio-документ mp3/wav/ogg.")
        path = self.tmp_path(job_id, suffix)
        await self.bot.download(file_id, destination=path)
        self._check_size(path, self.settings.max_audio_file_bytes)
        if suffix.lower() == ".ogg" and convert_voice:
            converted = path.with_suffix(".mp3")
            await self.convert_audio(path, converted)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            path = converted
            self._check_size(path, self.settings.max_audio_file_bytes)
        return path, file_id

    async def download_image_file_id(self, file_id: str, job_id: int) -> Path:
        file = await self.bot.get_file(file_id)
        suffix = Path(file.file_path or "").suffix or ".jpg"
        path = self.tmp_path(job_id, suffix)
        await self.bot.download(file_id, destination=path)
        self._check_size(path, self.settings.max_image_file_bytes)
        return path

    async def download_audio_file_id(self, file_id: str, job_id: int) -> Path:
        file = await self.bot.get_file(file_id)
        suffix = Path(file.file_path or "").suffix or ".mp3"
        path = self.tmp_path(job_id, suffix)
        await self.bot.download(file_id, destination=path)
        self._check_size(path, self.settings.max_audio_file_bytes)
        if suffix.lower() in {".ogg", ".oga"}:
            converted = path.with_suffix(".mp3")
            await self.convert_audio(path, converted)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            path = converted
            self._check_size(path, self.settings.max_audio_file_bytes)
        return path

    async def convert_audio(self, source: Path, target: Path) -> None:
        if not shutil.which("ffmpeg"):
            raise FileValidationError("ffmpeg недоступен. Невозможно конвертировать voice-сообщение.")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "192k",
            str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="ignore")[-400:]
            raise FileValidationError(f"Не удалось конвертировать аудио через ffmpeg. {detail}")

    def _validate_document_image(self, document: Document) -> None:
        if document.mime_type not in IMAGE_MIME:
            raise FileValidationError("Поддерживаются изображения JPG и PNG.")
        if document.file_size and document.file_size > self.settings.max_image_file_bytes:
            raise FileValidationError("Файл слишком большой.")

    def _validate_document_audio(self, document: Document) -> None:
        if document.mime_type not in AUDIO_MIME:
            raise FileValidationError("Поддерживаются аудио mp3/wav/ogg.")
        if document.file_size and document.file_size > self.settings.max_audio_file_bytes:
            raise FileValidationError("Файл слишком большой.")

    @staticmethod
    def _check_size(path: Path, limit: int) -> None:
        if path.stat().st_size > limit:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise FileValidationError("Файл слишком большой.")


def _suffix_from_name_or_mime(name: str | None, mime: str | None, default: str) -> str:
    if name:
        suffix = Path(sanitize_filename_part(name)).suffix
        if suffix:
            return suffix
    return mimetypes.guess_extension(mime or "") or default
