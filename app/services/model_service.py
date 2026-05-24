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

    async def list_avatar_video_models(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT * FROM hedra_models")
        models = [dict(row) for row in rows]
        preferred = [model for model in models if _is_recommended_avatar_model(model)]
        if preferred:
            return sorted(preferred, key=_model_sort_key)
        fallback = [model for model in models if _is_video(model)]
        return sorted(fallback, key=_model_sort_key)

    async def set_video_model(self, model_id: str) -> bool:
        row = await self.db.fetchone("SELECT id FROM hedra_models WHERE id=?", (model_id,))
        if not row:
            return False
        await self.db.set_setting("selected_video_model_id", model_id)
        return True

    async def set_preferred_by_name(self, preferred: str) -> dict[str, Any] | None:
        rows = await self.db.fetchall("SELECT * FROM hedra_models")
        models = [dict(row) for row in rows]
        preferred_lower = preferred.lower()
        candidates = [model for model in models if preferred_lower in (model.get("name") or "").lower()]
        if preferred_lower in {"character", "character 3", "hedra character 3"}:
            candidates = [
                model for model in models
                if "character" in (model.get("name") or "").lower() and ("3" in (model.get("name") or "") or "iii" in (model.get("name") or "").lower())
            ] or [model for model in models if "character" in (model.get("name") or "").lower()]
        if preferred_lower in {"omnia", "hedra omnia"}:
            candidates = [model for model in models if "omnia" in (model.get("name") or "").lower()]
        candidates = [model for model in candidates if _is_video(model)] or candidates
        if not candidates:
            return None
        chosen = sorted(candidates, key=_model_sort_key)[0]
        await self.db.set_setting("selected_video_model_id", chosen["id"])
        return chosen

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


def _is_recommended_avatar_model(model: dict[str, Any]) -> bool:
    text = f"{model.get('name') or ''} {model.get('type') or ''} {model.get('raw_json') or ''}".lower()
    if not _is_video(model):
        return False
    return "omnia" in text or "character" in text or "avatar" in text


def _model_sort_key(model: dict[str, Any]) -> tuple[int, str]:
    text = f"{model.get('name') or ''} {model.get('raw_json') or ''}".lower()
    if "omnia" in text:
        rank = 0
    elif "character" in text and "3" in text:
        rank = 1
    elif "character" in text:
        rank = 2
    elif "avatar" in text:
        rank = 3
    else:
        rank = 9
    return rank, model.get("name") or model.get("id") or ""
