from __future__ import annotations

import asyncio
from pathlib import Path

from app.hedra_client import HedraClient, extract_asset_url
from app.services.model_adapters import HedraGrokImagineI2IAdapter


def test_extract_asset_url_prefers_uploaded_asset_url() -> None:
    response = {
        "thumbnail_url": "https://cdn.hedra/thumb.png",
        "asset": {
            "url": "https://cdn.hedra/source.png",
            "type": "uploaded_image",
        },
    }

    assert extract_asset_url(response) == "https://cdn.hedra/source.png"


def test_extract_asset_url_does_not_use_thumbnail_by_default() -> None:
    response = {"thumbnail_url": "https://cdn.hedra/thumb.png"}

    assert extract_asset_url(response) is None
    assert extract_asset_url(response, allow_thumbnail=True) == "https://cdn.hedra/thumb.png"


def test_try_get_asset_url_uses_exact_asset_id_only() -> None:
    async def run() -> None:
        client = object.__new__(HedraClient)
        client._asset_urls = {}

        async def get_asset(asset_id: str) -> dict:
            return {"id": "old", "asset": {"url": "https://cdn.hedra/old.png"}}

        async def list_assets(asset_type: str | None = None, ids: str | None = None) -> list[dict]:
            return [
                {"id": "old", "asset": {"url": "https://cdn.hedra/old.png"}},
                {"id": "target", "asset": {"url": "https://cdn.hedra/target.png"}},
            ]

        client.get_asset = get_asset
        client.list_assets = list_assets

        assert await client.try_get_asset_url("target") == "https://cdn.hedra/target.png"
        assert await client.try_get_asset_url("missing") is None

    asyncio.run(run())


def test_grok_i2i_adapter_uses_current_job_image_url(tmp_path: Path) -> None:
    async def run() -> None:
        image_path = tmp_path / "source.png"
        image_path.write_bytes(b"fake-image")
        adapter = HedraGrokImagineI2IAdapter({}, "Grok Imagine I2I")
        prepared = await adapter.build(
            hedra_client=object.__new__(HedraClient),
            image_asset_id="asset-a",
            image_url="https://cdn.hedra/A.png",
            local_image_path=image_path,
            model_id="model",
            text_prompt="edit",
            aspect_ratio="1:1",
            resolution="1080p",
        )

        assert prepared.payload["image_url"] == "https://cdn.hedra/A.png"
        assert "reference_image_ids" not in prepared.payload

    asyncio.run(run())


def test_two_i2i_payloads_do_not_mix_urls(tmp_path: Path) -> None:
    async def run() -> None:
        image_path = tmp_path / "source.png"
        image_path.write_bytes(b"fake-image")
        adapter = HedraGrokImagineI2IAdapter({}, "Grok Imagine I2I")
        payload_a = await adapter.build(
            hedra_client=object.__new__(HedraClient),
            image_asset_id="asset-a",
            image_url="https://cdn.hedra/A.png",
            local_image_path=image_path,
            model_id="model",
            text_prompt="edit a",
            aspect_ratio="1:1",
            resolution="1080p",
        )
        payload_b = await adapter.build(
            hedra_client=object.__new__(HedraClient),
            image_asset_id="asset-b",
            image_url="https://cdn.hedra/B.png",
            local_image_path=image_path,
            model_id="model",
            text_prompt="edit b",
            aspect_ratio="1:1",
            resolution="1080p",
        )

        assert payload_a.payload["image_url"] == "https://cdn.hedra/A.png"
        assert payload_b.payload["image_url"] == "https://cdn.hedra/B.png"
        assert "B.png" not in str(payload_a.payload)
        assert "A.png" not in str(payload_b.payload)

    asyncio.run(run())
