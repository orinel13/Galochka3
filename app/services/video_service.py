from __future__ import annotations

from app.config import Settings
from app.hedra_client import HedraClient


class VideoService:
    def __init__(self, hedra: HedraClient, settings: Settings) -> None:
        self.hedra = hedra
        self.settings = settings

    async def with_audio(self, image_asset_id: str, audio_asset_id: str, model_id: str, text_prompt: str | None = None) -> dict:
        return await self.hedra.generate_avatar_video_with_audio(
            image_asset_id=image_asset_id,
            audio_asset_id=audio_asset_id,
            model_id=model_id,
            aspect_ratio=self.settings.default_video_aspect_ratio,
            resolution=self.settings.default_video_resolution,
            text_prompt=text_prompt,
        )

    async def with_inline_tts(self, image_asset_id: str, voice_id: str, text: str, model_id: str, text_prompt: str | None = None) -> dict:
        return await self.hedra.generate_avatar_video_with_inline_tts(
            image_asset_id=image_asset_id,
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            aspect_ratio=self.settings.default_video_aspect_ratio,
            resolution=self.settings.default_video_resolution,
            stability=self.settings.default_tts_stability,
            speed=self.settings.default_tts_speed,
            language=self.settings.default_language,
            text_prompt=text_prompt,
        )
