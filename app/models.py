from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    UPLOADING_ASSETS = "uploading_assets"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    DOWNLOADING = "downloading"
    COMPLETE = "complete"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobType(StrEnum):
    TTS = "tts"
    VIDEO_FROM_TEXT = "video_from_text"
    VIDEO_FROM_UPLOADED_AUDIO = "video_from_uploaded_audio"
    VIDEO_FROM_GENERATED_AUDIO = "video_from_generated_audio"


AUDIO_JOB_TYPES = {JobType.TTS.value}
VIDEO_JOB_TYPES = {
    JobType.VIDEO_FROM_TEXT.value,
    JobType.VIDEO_FROM_UPLOADED_AUDIO.value,
    JobType.VIDEO_FROM_GENERATED_AUDIO.value,
}

VIDEO_PROMPT = "A person speaking naturally to the camera with clear lip sync."
