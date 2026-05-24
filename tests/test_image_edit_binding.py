from __future__ import annotations

import asyncio
from pathlib import Path

from app.hedra_client import HedraClient, extract_asset_url
from app.jobs import extract_result_asset_id
from app.services.model_adapters import HedraGrokImagineI2IAdapter, HedraImageEditAdapter


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


def test_grok_i2i_adapter_uses_current_job_asset_id(tmp_path: Path) -> None:
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

        assert prepared.payload["type"] == "image_to_image"
        assert prepared.payload["reference_image_ids"] == ["asset-a"]
        assert "image_url" not in prepared.payload
        assert prepared.input_image_url == "https://cdn.hedra/A.png"

    asyncio.run(run())


def test_generic_image_edit_falls_back_to_current_file_data_uri(tmp_path: Path) -> None:
    async def run() -> None:
        image_path = tmp_path / "source.png"
        image_path.write_bytes(b"fake-image")
        client = object.__new__(HedraClient)
        adapter = HedraImageEditAdapter({}, "Generic I2I")
        prepared = await adapter.build(
            hedra_client=client,
            image_asset_id="asset-a",
            image_url=None,
            local_image_path=image_path,
            model_id="model",
            text_prompt="edit",
            aspect_ratio="1:1",
            resolution="1080p",
        )

        assert prepared.payload["image_url"].startswith("data:image/png;base64,")
        assert prepared.input_image_source == "data_uri_current_file"

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

        assert payload_a.payload["reference_image_ids"] == ["asset-a"]
        assert payload_b.payload["reference_image_ids"] == ["asset-b"]
        assert payload_a.input_image_url == "https://cdn.hedra/A.png"
        assert payload_b.input_image_url == "https://cdn.hedra/B.png"
        assert "asset-b" not in str(payload_a.payload)
        assert "asset-a" not in str(payload_b.payload)

    asyncio.run(run())


def test_result_asset_id_is_extracted_from_batch_results() -> None:
    status = {
        "status": "complete",
        "batch_results": [
            {"id": "generation-a", "asset_id": "asset-a", "status": "complete"},
        ],
    }

    assert extract_result_asset_id(status, "image") == "asset-a"
