from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.utils import now_iso, parse_iso

logger = logging.getLogger(__name__)


class CleanupService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> int:
        rows = await self.db.fetchall(
            "SELECT id, local_result_path, expires_at FROM jobs WHERE local_result_path IS NOT NULL AND expires_at IS NOT NULL"
        )
        removed = 0
        now = datetime.now(UTC)
        for row in rows:
            expires = parse_iso(row["expires_at"])
            if not expires or expires > now:
                continue
            path = Path(row["local_result_path"])
            if path.exists() and _inside(path, self.settings.tmp_dir):
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning("Failed to remove tmp file %s: %s", path, exc)
            await self.db.execute("UPDATE jobs SET local_result_path=NULL, updated_at=? WHERE id=?", (now_iso(), row["id"]))
        return removed

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Cleanup service failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=3600)
            except asyncio.TimeoutError:
                continue


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
