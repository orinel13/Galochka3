from __future__ import annotations

from app.config import Settings
from app.hedra_client import HedraClient


class TtsService:
    def __init__(self, hedra: HedraClient, settings: Settings) -> None:
        self.hedra = hedra
        self.settings = settings

    async def generate(self, voice_id: str, text: str) -> dict:
        return await self.hedra.generate_tts(
            voice_id=voice_id,
            text=text,
            stability=self.settings.default_tts_stability,
            speed=self.settings.default_tts_speed,
            language=self.settings.default_language,
        )
