from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.hedra_client import HedraClient

logger = logging.getLogger(__name__)


class ModelAdapterError(RuntimeError):
    pass


@dataclass
class PreparedPayload:
    adapter_name: str
    payload: dict[str, Any]
    payload_keys: list[str]
    input_image_url: str | None = None
    input_image_asset_id: str | None = None


class BaseModelAdapter:
    name = "base"

    def __init__(self, model_raw_json: dict[str, Any] | str | None, model_name: str = "") -> None:
        self.model_raw_json = _loads_model(model_raw_json)
        self.model_name = model_name
        self.raw_text = json.dumps(self.model_raw_json, ensure_ascii=False).lower()
        self.name_text = model_name.lower()


class HedraImageGenerationAdapter(BaseModelAdapter):
    name = "hedra_image_generation"

    async def build(
        self,
        *,
        model_id: str,
        text_prompt: str,
        aspect_ratio: str,
        resolution: str,
        batch_size: int = 1,
        enhance_prompt: bool = False,
    ) -> PreparedPayload:
        payload = {
            "type": "image",
            "text_prompt": text_prompt,
            "ai_model_id": model_id,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "batch_size": batch_size,
            "enhance_prompt": enhance_prompt,
        }
        return PreparedPayload(self.name, payload, list(payload.keys()))


class HedraImageEditAdapter(BaseModelAdapter):
    name = "hedra_image_edit"

    async def build(
        self,
        *,
        hedra_client: HedraClient,
        image_asset_id: str,
        local_image_path: Path,
        model_id: str,
        text_prompt: str,
        aspect_ratio: str,
        resolution: str,
        batch_size: int = 1,
    ) -> PreparedPayload:
        reference = await prepare_image_reference_for_edit(hedra_client, image_asset_id, local_image_path, self.model_raw_json)
        payload = {
            "type": "image",
            "text_prompt": text_prompt,
            "ai_model_id": model_id,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "batch_size": batch_size,
        }
        payload.update(reference["payload"])
        return PreparedPayload(
            self.name,
            payload,
            list(payload.keys()),
            input_image_url=reference.get("image_url"),
            input_image_asset_id=image_asset_id,
        )


class HedraGrokImagineI2IAdapter(HedraImageEditAdapter):
    name = "hedra_grok_imagine_i2i"


class HedraVideoI2VAdapter(BaseModelAdapter):
    name = "hedra_video_i2v"


class HedraAvatarVideoAdapter(BaseModelAdapter):
    name = "hedra_avatar_video"


def get_adapter_for_model(model_raw_json: dict[str, Any] | str | None, generation_family: str, model_name: str) -> BaseModelAdapter:
    text = f"{model_name} {model_raw_json or ''}".lower()
    if generation_family == "image_generation":
        return HedraImageGenerationAdapter(model_raw_json, model_name)
    if generation_family == "image_edit":
        if "grok" in text and ("i2i" in text or "imagine" in text):
            return HedraGrokImagineI2IAdapter(model_raw_json, model_name)
        return HedraImageEditAdapter(model_raw_json, model_name)
    if generation_family == "image_to_video":
        return HedraVideoI2VAdapter(model_raw_json, model_name)
    if generation_family == "avatar_video":
        return HedraAvatarVideoAdapter(model_raw_json, model_name)
    return BaseModelAdapter(model_raw_json, model_name)


async def prepare_image_reference_for_edit(
    hedra_client: HedraClient,
    image_asset_id: str,
    local_image_path: Path,
    model_raw_json: dict[str, Any] | str | None,
) -> dict[str, Any]:
    raw = _loads_model(model_raw_json)
    raw_text = json.dumps(raw, ensure_ascii=False).lower()
    image_url = await hedra_client.try_get_asset_url(image_asset_id)
    if image_url:
        field = _preferred_image_url_field(raw_text)
        if field == "image_urls":
            return {"payload": {"image_urls": [image_url]}, "image_url": image_url}
        if field == "images":
            return {"payload": {"images": [image_url]}, "image_url": image_url}
        if field == "reference_image_urls":
            return {"payload": {"reference_image_urls": [image_url]}, "image_url": image_url}
        return {"payload": {field: image_url}, "image_url": image_url}
    if "reference_image_ids" in raw_text:
        return {"payload": {"reference_image_ids": [image_asset_id]}, "image_url": None}
    if any(marker in raw_text for marker in ("image_id", "image_asset_id")):
        return {"payload": {"image_id": image_asset_id}, "image_url": None}
    if "base64" in raw_text or "data uri" in raw_text or "data:" in raw_text:
        return {"payload": {"image_url": hedra_client.build_data_uri(local_image_path)}, "image_url": None}
    raise ModelAdapterError(
        "Эта image model требует image URL/reference image, но текущий Hedra API не дал совместимый способ "
        "передать загруженное изображение. Попробуй другую image model."
    )


def _preferred_image_url_field(raw_text: str) -> str:
    for field in (
        "image_urls",
        "reference_image_urls",
        "source_image_url",
        "input_image_url",
        "reference_image_url",
        "image_url",
        "images",
    ):
        if field in raw_text:
            return field
    return "image_urls"


def fallback_image_url_payloads(image_url: str) -> list[dict[str, Any]]:
    return [
        {"image_urls": [image_url]},
        {"image_url": image_url},
        {"reference_image_urls": [image_url]},
        {"source_image_url": image_url},
        {"input_image_url": image_url},
    ]


def _loads_model(value: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {"raw": data}
        except ValueError:
            return {"raw": value}
    return {}
