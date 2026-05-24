from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.db import Database
from app.hedra_client import HedraClient
from app.utils import now_iso, sanitize_filename_part, short_error

logger = logging.getLogger(__name__)


class VoiceCloneService:
    def __init__(self, db: Database, hedra: HedraClient, poll_interval: int, timeout: int) -> None:
        self.db = db
        self.hedra = hedra
        self.poll_interval = poll_interval
        self.timeout = timeout

    async def clone_voice(self, voice_name: str, sample_path: Path) -> tuple[bool, str]:
        job_id = await self._create_job(voice_name)
        try:
            asset = await self.hedra.create_asset(f"voice_sample_{sanitize_filename_part(voice_name)}{sample_path.suffix}", "audio")
            asset_id = extract_id(asset)
            if not asset_id:
                raise RuntimeError("Hedra не вернула asset id для sample.")
            await self.db.execute(
                "UPDATE voice_clone_jobs SET sample_asset_id=?, updated_at=? WHERE id=?",
                (asset_id, now_iso(), job_id),
            )
            await self.hedra.upload_asset(asset_id, sample_path)
            generation = await self.hedra.generate_voice_clone(asset_id, voice_name)
            generation_id = extract_id(generation)
            if not generation_id:
                raise RuntimeError("Hedra не вернула generation id для voice clone.")
            await self.db.execute(
                "UPDATE voice_clone_jobs SET hedra_generation_id=?, status='processing', updated_at=? WHERE id=?",
                (generation_id, now_iso(), job_id),
            )
            status = await self._poll(generation_id)
            voice_id = extract_voice_id(status)
            if not voice_id:
                raise RuntimeError("Voice clone завершён, но Hedra не вернула resulting voice_id.")
            await self._add_voice(voice_name, voice_id)
            await self.db.execute(
                """
                UPDATE voice_clone_jobs
                SET resulting_voice_id=?, status='complete', updated_at=?
                WHERE id=?
                """,
                (voice_id, now_iso(), job_id),
            )
            return True, f"Голос создан: {voice_name}\nvoice_id: {voice_id}"
        except Exception as exc:
            logger.exception("Voice clone failed")
            message = short_error(str(exc))
            await self.db.execute(
                "UPDATE voice_clone_jobs SET status='error', error_message=?, updated_at=? WHERE id=?",
                (message, now_iso(), job_id),
            )
            return False, f"Voice clone завершился ошибкой: {message}"
        finally:
            try:
                sample_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to delete voice sample %s", sample_path)

    async def _create_job(self, name: str) -> int:
        cur = await self.db.execute(
            "INSERT INTO voice_clone_jobs (name, status, created_at, updated_at) VALUES (?, 'queued', ?, ?)",
            (name, now_iso(), now_iso()),
        )
        return int(cur.lastrowid)

    async def _poll(self, generation_id: str) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.timeout
        last: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline:
            last = await self.hedra.get_generation_status(generation_id)
            status = str(last.get("status") or last.get("state") or "").lower()
            if status in {"complete", "completed", "succeeded", "success", "done"}:
                return last
            if status in {"error", "failed", "failure", "cancelled"}:
                raise RuntimeError(str(last.get("error") or last.get("message") or "Hedra вернула ошибку voice clone."))
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError("Voice clone не успел завершиться за лимит времени.")

    async def _add_voice(self, name: str, voice_id: str) -> None:
        count = await self.db.fetchone("SELECT COUNT(*) AS c FROM voices")
        is_default = 1 if count and count["c"] == 0 else 0
        await self.db.execute(
            """
            INSERT INTO voices (name, hedra_voice_id, source, is_active, is_default, created_at, updated_at)
            VALUES (?, ?, 'hedra_voice_clone', 1, ?, ?, ?)
            ON CONFLICT(hedra_voice_id) DO UPDATE SET
              name=excluded.name,
              source=excluded.source,
              is_active=1,
              updated_at=excluded.updated_at
            """,
            (name, voice_id, is_default, now_iso(), now_iso()),
        )


def extract_id(data: dict[str, Any]) -> str | None:
    for key in ("id", "generation_id", "asset_id", "uuid"):
        value = data.get(key)
        if value:
            return str(value)
    nested = data.get("data")
    if isinstance(nested, dict):
        return extract_id(nested)
    return None


def extract_voice_id(data: dict[str, Any]) -> str | None:
    for key in ("voice_id", "resulting_voice_id", "hedra_voice_id", "asset_id", "id"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("result", "data", "voice", "asset"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_voice_id(nested)
            if found:
                return found
    return None
