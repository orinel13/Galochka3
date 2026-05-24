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
            description = str(model.get("description") or model.get("summary") or "")
            model_type = model.get("type") or model.get("model_type") or ""
            raw = json.dumps(model, ensure_ascii=False)
            await self.db.execute(
                """
                INSERT INTO hedra_models
                  (id, name, description, type, supports_1_1, supports_9_16, supports_16_9,
                   supports_540p, supports_720p, supports_1080p, supports_1440p, supports_2160p,
                   requires_start_frame, requires_end_frame, requires_audio_input, requires_input_video,
                   max_duration_ms, billing_unit, credit_cost, credits_per_second, premium, raw_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  description=excluded.description,
                  type=excluded.type,
                  supports_1_1=excluded.supports_1_1,
                  supports_9_16=excluded.supports_9_16,
                  supports_16_9=excluded.supports_16_9,
                  supports_540p=excluded.supports_540p,
                  supports_720p=excluded.supports_720p,
                  supports_1080p=excluded.supports_1080p,
                  supports_1440p=excluded.supports_1440p,
                  supports_2160p=excluded.supports_2160p,
                  requires_start_frame=excluded.requires_start_frame,
                  requires_end_frame=excluded.requires_end_frame,
                  requires_audio_input=excluded.requires_audio_input,
                  requires_input_video=excluded.requires_input_video,
                  max_duration_ms=excluded.max_duration_ms,
                  billing_unit=excluded.billing_unit,
                  credit_cost=excluded.credit_cost,
                  credits_per_second=excluded.credits_per_second,
                  premium=excluded.premium,
                  raw_json=excluded.raw_json,
                  updated_at=excluded.updated_at
                """,
                (
                    model_id,
                    name,
                    description,
                    str(model_type) if model_type is not None else None,
                    int(_contains_1_1(model)),
                    int(_contains_text(model, "9:16") or _contains_text(model, "9x16")),
                    int(_contains_text(model, "16:9") or _contains_text(model, "16x9")),
                    int(_contains_text(model, "540p")),
                    int(_contains_text(model, "720p")),
                    int(_contains_text(model, "1080p")),
                    int(_contains_text(model, "1440p")),
                    int(_contains_text(model, "2160p") or _contains_text(model, "4k")),
                    int(_truthy(model, "requires_start_frame", "requiresStartFrame", "start_frame_required")),
                    int(_truthy(model, "requires_end_frame", "requiresEndFrame", "end_frame_required")),
                    int(_truthy(model, "requires_audio_input", "requiresAudioInput", "audio_required")),
                    int(_truthy(model, "requires_input_video", "requiresInputVideo", "input_video_required")),
                    _max_duration(model),
                    _billing_unit(model),
                    _credit_cost(model),
                    _credits_per_second(model),
                    int(_truthy(model, "premium", "is_premium", "paid")),
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

    async def compatible_avatar_models(self, aspect_ratio: str = "1:1", resolution: str = "540p") -> list[dict[str, Any]]:
        return [
            model for model in await self.list_avatar_video_models()
            if is_avatar_compatible(model, aspect_ratio, resolution)
        ]

    async def compatible_video_models(self, aspect_ratio: str = "1:1", resolution: str = "540p") -> list[dict[str, Any]]:
        models = await self.list_models()
        return sorted(
            [model for model in models if is_image_to_video_compatible(model, aspect_ratio, resolution)],
            key=_model_sort_key,
        )

    async def compatible_image_models(self, aspect_ratio: str = "1:1", resolution: str = "1080p") -> list[dict[str, Any]]:
        models = await self.list_models()
        return sorted(
            [model for model in models if is_image_model(model, aspect_ratio, resolution)],
            key=_model_sort_key,
        )

    async def set_video_model(self, model_id: str) -> bool:
        row = await self.db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
        if not row:
            return False
        await self.db.set_setting("selected_video_model_id", model_id)
        await self.db.set_setting("selected_video_model_name", row["name"])
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

    async def selected_model_for_user(self, telegram_id: int, family: str) -> dict[str, Any] | None:
        user_settings = await self.db.get_user_settings(telegram_id)
        id_key = f"selected_{family}_model_id"
        model_id = user_settings[id_key] if id_key in user_settings.keys() else None
        if not model_id:
            model_id = await self.db.get_setting(id_key)
        if not model_id:
            return None
        row = await self.db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
        return dict(row) if row else None

    async def set_user_model(self, telegram_id: int, family: str, model_id: str) -> bool:
        row = await self.db.fetchone("SELECT * FROM hedra_models WHERE id=?", (model_id,))
        if not row:
            return False
        await self.db.update_user_settings(
            telegram_id,
            **{
                f"selected_{family}_model_id": row["id"],
                f"selected_{family}_model_name": row["name"],
            },
        )
        return True

    async def choose_default_avatar_model(self) -> str | None:
        avatar_selected = await self.db.get_setting("selected_avatar_model_id")
        if avatar_selected:
            row = await self.db.fetchone("SELECT id FROM hedra_models WHERE id=?", (avatar_selected,))
            if row:
                return avatar_selected
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

    async def choose_default_image_model(self) -> str | None:
        selected = await self.db.get_setting("selected_image_model_id")
        if selected:
            row = await self.db.fetchone("SELECT id FROM hedra_models WHERE id=?", (selected,))
            if row:
                return selected
        rows = await self.compatible_image_models()
        return rows[0]["id"] if rows else None


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


def _truthy(model: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = model.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        if isinstance(value, str) and value.lower() in {"true", "yes", "required"}:
            return True
    text = json.dumps(model, ensure_ascii=False).lower()
    return any(key.lower() in text and "true" in text for key in keys)


def _billing_unit(model: dict[str, Any]) -> str | None:
    for key in ("billing_unit", "billingUnit", "unit"):
        if model.get(key):
            return str(model[key])
    return None


def _credit_cost(model: dict[str, Any]) -> int | None:
    for key in ("credit_cost", "creditCost", "credits", "cost"):
        try:
            if model.get(key) is not None:
                return int(model[key])
        except (TypeError, ValueError):
            continue
    return None


def _credits_per_second(model: dict[str, Any]) -> float | None:
    for key in ("credits_per_second", "creditsPerSecond"):
        try:
            if model.get(key) is not None:
                return float(model[key])
        except (TypeError, ValueError):
            continue
    return None


def _is_video(model: dict[str, Any]) -> bool:
    text = f"{model.get('type') or ''} {model.get('name') or ''} {model.get('raw_json') or ''}".lower()
    return "video" in text or "avatar" in text or "character" in text


def _supports_aspect(model: dict[str, Any], aspect_ratio: str) -> bool:
    if aspect_ratio == "1:1":
        return bool(model.get("supports_1_1")) or _contains_1_1(model)
    if aspect_ratio == "9:16":
        return bool(model.get("supports_9_16")) or _contains_text(model, "9:16") or _contains_text(model, "9x16")
    if aspect_ratio == "16:9":
        return bool(model.get("supports_16_9")) or _contains_text(model, "16:9") or _contains_text(model, "16x9")
    return True


def _supports_resolution(model: dict[str, Any], resolution: str) -> bool:
    key = f"supports_{resolution}".replace("p", "p")
    return bool(model.get(key)) or _contains_text(model, resolution)


def is_avatar_compatible(model: dict[str, Any], aspect_ratio: str = "1:1", resolution: str = "540p") -> bool:
    text = f"{model.get('name') or ''} {model.get('type') or ''} {model.get('raw_json') or ''}".lower()
    return _is_video(model) and _supports_aspect(model, aspect_ratio) and (
        "avatar" in text or "character" in text or "lip" in text or "audio" in text or "omnia" in text
    )


def is_image_to_video_compatible(model: dict[str, Any], aspect_ratio: str = "1:1", resolution: str = "540p") -> bool:
    if not _is_video(model) or model.get("requires_audio_input"):
        return False
    return _supports_aspect(model, aspect_ratio) and (_supports_resolution(model, resolution) or resolution == "540p")


def is_image_model(model: dict[str, Any], aspect_ratio: str = "1:1", resolution: str = "1080p") -> bool:
    text = f"{model.get('type') or ''} {model.get('name') or ''} {model.get('raw_json') or ''}".lower()
    if "image" not in text and "imagine" not in text and "banana" not in text:
        return False
    return _supports_aspect(model, aspect_ratio) or not any(model.get(k) for k in ("supports_1_1", "supports_9_16", "supports_16_9"))


def supports_image_edit(model: dict[str, Any]) -> bool:
    text = f"{model.get('name') or ''} {model.get('description') or ''} {model.get('raw_json') or ''}".lower()
    return any(marker in text for marker in ("image edit", "edit image", "reference image", "image-to-image", "input_image", "image_id"))


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
