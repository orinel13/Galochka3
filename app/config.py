from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    hedra_api_key: str
    admin_telegram_id: int
    database_path: Path
    data_dir: Path
    tmp_dir: Path
    log_file: Path
    default_language: str
    default_tts_stability: float
    default_tts_speed: float
    default_video_aspect_ratio: str
    default_video_resolution: str
    default_image_aspect_ratio: str
    default_image_resolution: str
    default_avatar_prompt: str
    default_video_prompt: str
    default_image_prompt: str
    default_image_edit_prompt: str
    default_video_no_audio_prompt: str
    max_text_chars_tts: int
    max_text_chars_video: int
    max_audio_file_mb: int
    max_image_file_mb: int
    job_poll_interval_sec: int
    job_timeout_sec: int
    tmp_file_ttl_hours: int
    max_parallel_audio_jobs: int
    max_parallel_video_jobs: int
    allow_new_users: bool
    hedra_base_url: str = "https://api.hedra.com/web-app/public"

    @property
    def max_audio_file_bytes(self) -> int:
        return self.max_audio_file_mb * 1024 * 1024

    @property
    def max_image_file_bytes(self) -> int:
        return self.max_image_file_mb * 1024 * 1024


def load_settings(require_secrets: bool = True) -> Settings:
    load_dotenv()
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    hedra_api_key = os.getenv("HEDRA_API_KEY", "").strip()
    admin_raw = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
    missing = []
    if require_secrets and not bot_token:
        missing.append("BOT_TOKEN")
    if require_secrets and not hedra_api_key:
        missing.append("HEDRA_API_KEY")
    if require_secrets and not admin_raw:
        missing.append("ADMIN_TELEGRAM_ID")
    if missing:
        raise RuntimeError("Не заполнены обязательные переменные окружения: " + ", ".join(missing))

    admin_id = int(admin_raw) if admin_raw else 0
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    tmp_dir = Path(os.getenv("TMP_DIR", str(data_dir / "tmp")))
    log_file = Path(os.getenv("LOG_FILE", str(data_dir / "logs" / "galochka.log")))
    return Settings(
        bot_token=bot_token,
        hedra_api_key=hedra_api_key,
        admin_telegram_id=admin_id,
        database_path=Path(os.getenv("DATABASE_PATH", str(data_dir / "galochka.db"))),
        data_dir=data_dir,
        tmp_dir=tmp_dir,
        log_file=log_file,
        default_language=os.getenv("DEFAULT_LANGUAGE", "auto"),
        default_tts_stability=_float("DEFAULT_TTS_STABILITY", 0.5),
        default_tts_speed=_float("DEFAULT_TTS_SPEED", 1.0),
        default_video_aspect_ratio=os.getenv("DEFAULT_VIDEO_ASPECT_RATIO", "1:1"),
        default_video_resolution=os.getenv("DEFAULT_VIDEO_RESOLUTION", "540p"),
        default_image_aspect_ratio=os.getenv("DEFAULT_IMAGE_ASPECT_RATIO", "1:1"),
        default_image_resolution=os.getenv("DEFAULT_IMAGE_RESOLUTION", "1080p"),
        default_avatar_prompt=os.getenv("DEFAULT_AVATAR_PROMPT", "A person speaking naturally to the camera with clear lip sync."),
        default_video_prompt=os.getenv("DEFAULT_VIDEO_PROMPT", "A person looking natural on camera."),
        default_image_prompt=os.getenv("DEFAULT_IMAGE_PROMPT", ""),
        default_image_edit_prompt=os.getenv("DEFAULT_IMAGE_EDIT_PROMPT", ""),
        default_video_no_audio_prompt=os.getenv(
            "DEFAULT_VIDEO_NO_AUDIO_PROMPT",
            "Subtle natural camera motion, realistic movement, stable identity, cinematic lighting.",
        ),
        max_text_chars_tts=_int("MAX_TEXT_CHARS_TTS", 2500),
        max_text_chars_video=_int("MAX_TEXT_CHARS_VIDEO", 1200),
        max_audio_file_mb=_int("MAX_AUDIO_FILE_MB", 10),
        max_image_file_mb=_int("MAX_IMAGE_FILE_MB", 10),
        job_poll_interval_sec=_int("JOB_POLL_INTERVAL_SEC", 5),
        job_timeout_sec=_int("JOB_TIMEOUT_SEC", 1800),
        tmp_file_ttl_hours=_int("TMP_FILE_TTL_HOURS", 24),
        max_parallel_audio_jobs=_int("MAX_PARALLEL_AUDIO_JOBS", 2),
        max_parallel_video_jobs=_int("MAX_PARALLEL_VIDEO_JOBS", 1),
        allow_new_users=_bool(os.getenv("ALLOW_NEW_USERS"), False),
    )


def ensure_data_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "backups").mkdir(parents=True, exist_ok=True)
