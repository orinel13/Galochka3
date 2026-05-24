from __future__ import annotations

import json
from typing import Any

from app.db import Database
from app.hedra_client import HedraClient
from app.utils import now_iso


class ModelService:
    def __init__(self, db: Database, hedra: HedraClient) -> None:
        self.db = db
        self.hedra = hedra

    async def sync_models(self) -> int:
        models = await self.hedra.list_models()
        now = now_iso()
        for model in models:
            model_id = str(model.get("id") or model.get("model_id") or model.get("uuid") or "")
            if not model_id:
                continue
            name = str(model.get("name") or model.get("display_name") or model_id)
            model_type = model.get("type") or model.get("model_type") or ""
            raw = json.dumps(model, ensure_ascii=False)
            await self.db.execute(
                """
                INSERT INTO hedra_models
                  (id, name, type, supports_1_1, supports_540p, supports_720p, max_duration_ms, raw_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  type=excluded.type,
                  supports_1_1=excluded.supports_1_1,
                  supports_540p=excluded.supports_540p,
                  supports_720p=excluded.supports_720p,
                  max_duration_ms=excluded.max_duration_ms,
                  raw_json=excluded.raw_json,
                  updated_at=excluded.updated_at
                """,
                (
                    model_id,
                    name,
                    str(model_type) if model_type is not None else None,
                    int(_contains_1_1(model)),
                    int(_contains_text(model, "540p")),
                    int(_contains_text(model, "720p")),
                    _max_duration(model),
                    raw,
                    now,
                ),
            )
        return len(models)

    async def list_models(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT * FROM hedra_models ORDER BY name")
        return [dict(row) for row in rows]

    async def set_video_model(self, model_id: str) -> bool:
        row = await self.db.fetchone("SELECT id FROM hedra_models WHERE id=?", (model_id,))
        if not row:
            return False
        await self.db.set_setting("selected_video_model_id", model_id)
        return True

    async def selected_video_model_id(self) -> str | None:
        value = await self.db.get_setting("selected_video_model_id")
        if not value:
            return None
        row = await self.db.fetchone("SELECT id FROM hedra_models WHERE id=?", (value,))
        return value if row else None

    async def choose_default_avatar_model(self) -> str | None:
        selected = await self.selected_video_model_id()
        if selected:
            return selected
        rows = await self.db.fetchall("SELECT * FROM hedra_models")
        models = [dict(row) for row in rows]
        for model in models:
            if _is_video(model) and model.get("supports_1_1") and "hedra avatar" in model["name"].lower():
                return model["id"]
        for model in models:
            if _is_video(model) and model.get("supports_1_1") and "character" in model["name"].lower():
                return model["id"]
        for model in models:
            raw = (model.get("raw_json") or "").lower()
            if _is_video(model) and ("1:1" in raw or "avatar" in raw or "character" in raw):
                return model["id"]
        return None


def _contains_text(model: dict[str, Any], needle: str) -> bool:
    return needle.lower() in json.dumps(model, ensure_ascii=False).lower()


def _contains_1_1(model: dict[str, Any]) -> bool:
    text = json.dumps(model, ensure_ascii=False).lower()
    return "1:1" in text or "1x1" in text or '"square"' in text


def _max_duration(model: dict[str, Any]) -> int | None:
    for key in ("max_duration_ms", "maxDurationMs", "maximum_duration_ms"):
        value = model.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _is_video(model: dict[str, Any]) -> bool:
    text = f"{model.get('type') or ''} {model.get('name') or ''} {model.get('raw_json') or ''}".lower()
    return "video" in text or "avatar" in text or "character" in text
