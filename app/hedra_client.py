from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiohttp

from app.models import VIDEO_PROMPT
from app.utils import compact_json

logger = logging.getLogger(__name__)


class HedraApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


class HedraAuthError(HedraApiError):
    pass


class HedraClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        timeout = aiohttp.ClientTimeout(total=120)
        self.session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        await self.session.close()

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        data: Any | None = None,
        files: dict[str, Path] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"X-API-Key": self.api_key}
        retriable = {429, 500, 502, 503, 504}
        last_error: HedraApiError | None = None
        for attempt in range(5):
            handles = []
            try:
                body = data
                if files:
                    form = aiohttp.FormData()
                    for key, file_path in files.items():
                        handle = file_path.open("rb")
                        handles.append(handle)
                        form.add_field(key, handle, filename=file_path.name)
                    body = form
                async with self.session.request(method, url, headers=headers, json=json, data=body, params=params) as response:
                    request_id = response.headers.get("x-request-id") or response.headers.get("X-Request-Id")
                    text = await response.text()
                    payload = _loads(text)
                    if 200 <= response.status < 300:
                        return payload
                    message = _human_error(response.status, payload, text)
                    logger.warning(
                        "Hedra error status=%s endpoint=%s request_id=%s error=%s raw=%s",
                        response.status,
                        path,
                        request_id,
                        message,
                        compact_json(payload if payload is not None else text),
                    )
                    if response.status == 401:
                        raise HedraAuthError("Hedra вернула ошибку авторизации. Проверь HEDRA_API_KEY.", response.status, payload)
                    error = HedraApiError(message, response.status, payload)
                    if response.status not in retriable:
                        raise error
                    last_error = error
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = HedraApiError(f"Ошибка соединения с Hedra: {exc}")
                logger.warning("Hedra transport error endpoint=%s error=%s", path, exc)
            finally:
                for handle in handles:
                    handle.close()
            if attempt < 4:
                await asyncio.sleep(2**attempt)
        if last_error:
            raise last_error
        raise HedraApiError("Неизвестная ошибка Hedra.")

    async def get_credits(self) -> dict[str, Any]:
        data = await self._request("GET", "/billing/credits")
        return data if isinstance(data, dict) else {"raw": data}

    async def list_voices(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/voices")
        return _extract_list(data)

    async def list_models(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/models")
        return _extract_list(data)

    async def list_assets(self, asset_type: str | None = None) -> list[dict[str, Any]]:
        params = {"type": asset_type} if asset_type else None
        data = await self._request("GET", "/assets", params=params)
        return _extract_list(data)

    async def create_asset(self, name: str, asset_type: str) -> dict[str, Any]:
        data = await self._request("POST", "/assets", json={"name": name, "type": asset_type})
        return data if isinstance(data, dict) else {"raw": data}

    async def upload_asset(self, asset_id: str, file_path: Path) -> dict[str, Any]:
        data = await self._request("POST", f"/assets/{asset_id}/upload", files={"file": file_path})
        return data if isinstance(data, dict) else {"raw": data}

    async def generate_tts(self, voice_id: str, text: str, stability: float, speed: float, language: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/generations",
            json={
                "type": "text_to_speech",
                "voice_id": voice_id,
                "text": text,
                "stability": stability,
                "speed": speed,
                "language": language,
            },
        )

    async def generate_voice_clone(self, audio_asset_id: str, name: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/generations",
            json={"type": "voice_clone", "audio_id": audio_asset_id, "name": name},
        )

    async def generate_avatar_video_with_audio(
        self,
        image_asset_id: str,
        audio_asset_id: str,
        model_id: str,
        aspect_ratio: str,
        resolution: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/generations",
            json={
                "type": "video",
                "ai_model_id": model_id,
                "start_keyframe_id": image_asset_id,
                "audio_id": audio_asset_id,
                "generated_video_inputs": {
                    "text_prompt": VIDEO_PROMPT,
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                },
            },
        )

    async def generate_avatar_video_with_inline_tts(
        self,
        image_asset_id: str,
        voice_id: str,
        text: str,
        model_id: str,
        aspect_ratio: str,
        resolution: str,
        stability: float,
        speed: float,
        language: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/generations",
            json={
                "type": "video",
                "ai_model_id": model_id,
                "start_keyframe_id": image_asset_id,
                "audio_generation": {
                    "type": "text_to_speech",
                    "voice_id": voice_id,
                    "text": text,
                    "stability": stability,
                    "speed": speed,
                    "language": language,
                },
                "generated_video_inputs": {
                    "text_prompt": VIDEO_PROMPT,
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                },
            },
        )

    async def get_generation_status(self, generation_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/generations/{generation_id}/status")
        return data if isinstance(data, dict) else {"raw": data}

    async def download_file(self, url: str, output_path: Path) -> None:
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as response:
            if response.status >= 400:
                text = await response.text()
                raise HedraApiError(f"Не удалось скачать результат Hedra: HTTP {response.status} {text[:300]}", response.status)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("wb") as fh:
                async for chunk in response.content.iter_chunked(1024 * 256):
                    fh.write(chunk)


def _loads(text: str) -> Any:
    try:
        import json

        return json.loads(text) if text else {}
    except ValueError:
        return None


def _extract_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "voices", "models", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _human_error(status: int, payload: Any, text: str) -> str:
    if status == 401:
        return "Hedra вернула ошибку авторизации. Проверь HEDRA_API_KEY."
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error") or payload.get("detail")
        if message:
            return str(message)
    return f"Hedra вернула HTTP {status}: {text[:300]}"
