from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def iso_after_hours(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(stream)
    root.addHandler(file_handler)


def compact_json(data: Any, max_len: int = 1200) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(data)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...[truncated]"


def short_error(text: str | None, max_len: int = 700) -> str:
    if not text:
        return "Неизвестная ошибка."
    return text if len(text) <= max_len else text[:max_len] + "..."


def sanitize_filename_part(value: str) -> str:
    allowed = []
    for char in value.strip().replace(" ", "_"):
        if char.isalnum() or char in {"_", "-", "."}:
            allowed.append(char)
    cleaned = "".join(allowed).strip("._")
    return cleaned[:80] or "file"


def format_user(telegram_id: int, username: str | None, first_name: str | None, last_name: str | None) -> str:
    parts = [f"telegram_id: {telegram_id}"]
    if username:
        parts.append(f"username: @{username}")
    if first_name:
        parts.append(f"first_name: {first_name}")
    if last_name:
        parts.append(f"last_name: {last_name}")
    return "\n".join(parts)
