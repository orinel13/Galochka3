from __future__ import annotations

from typing import Any

from app.db import Database
from app.hedra_client import HedraClient


class CreditsService:
    def __init__(self, db: Database, hedra: HedraClient) -> None:
        self.db = db
        self.hedra = hedra

    async def get_credits(self, save_snapshot: bool = False) -> dict[str, Any]:
        data = await self.hedra.get_credits()
        if save_snapshot:
            await self.db.add_credit_snapshot(data)
        return data

    @staticmethod
    def remaining(data: dict[str, Any]) -> int | None:
        for key in ("remaining", "credits_remaining", "balance", "available"):
            value = data.get(key)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return None

    async def ensure_video_credits(self) -> tuple[bool, str | None]:
        data = await self.get_credits(save_snapshot=False)
        remaining = self.remaining(data)
        if remaining is not None and remaining <= 0:
            return False, "Недостаточно credits для генерации видео."
        return True, None
