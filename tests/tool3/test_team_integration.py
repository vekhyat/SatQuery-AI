"""The real repository's upload -> checker -> registry -> composer -> API contract."""
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from PIL import Image

from apps.web.server import create_web_app
from satquery.contracts import ResultEnvelope, ToolResult
from satquery.registry import TOOL_REGISTRY
from satquery.tools.tool3.pack_c import create_pack

QUESTION = "Use the optical and SAR images together to identify built-up and water-covered regions."


@pytest.fixture
def pack_c(tmp_path):
    return create_pack(tmp_path / "pack-c")


def attach(client, files, prefix=""):
    ids = []
    for path in files:
        response = client.post(prefix + "/upload", files={"file": (path.name, path.read_bytes(), "image/tiff")})
        assert response.status_code == 201, response.text
        ids.append(response.json()["asset_id"])
    return ids


def execute(client, ids, prefix=""):
    return client.post(prefix + "/query", json={"asset_ids": ids, "question": QUESTION})


def test_real_registry_pydantic_contract_and_three_layer_downloads(client, pack_c):
    ids = attach(client, reversed(pack_c))
    response = execute(client, ids)
    assert response.status_code == 200, response.text
    result = ResultEnvelope.model_validate(response.json())
    assert result.task == "optical_sar"
    assert result.tools[-1] == "optical_sar_v1"
    assert "optical_sar_v1" in TOOL_REGISTRY and "optical_sar_stub_v0" not in TOOL_REGISTRY
    assert result.receipt.trace[-1].status == "ok"
    assert result.receipt.trace[-1].details["fusion_rule"] == result.facts["fusion_rule"]
    assert result.facts["sar_contribution"] in result.answer_text
    assert result.facts["sar_added_water_pixels"] > 0
    assert result.facts["sar_added_builtup_pixels"] > 0
    assert result.confidence == 0 and "not calibrated" in result.facts["confidence_status"]
    assert "layers" not in response.json()  # Preserve M1's existing envelope.
    ToolResult.model_validate({key: response.json()[key] for key in ("facts", "confidence", "warnings", "overlay")})
    maps = {}
    for key, url in result.facts["layer_urls"].items():
        fetched = client.get(url)
        assert fetched.status_code == 200
        maps[key] = np.asarray(Image.open(BytesIO(fetched.content)))
    assert set(maps) == {"optical_only", "sar_only", "fused"}
    assert not np.array_equal(maps["optical_only"], maps["fused"])
    assert result.overlay.type == "heatmap" and result.overlay.file == result.facts["layer_urls"]["fused"]
    tif = client.get(result.facts["artifacts"]["fused.tif"])
    with rasterio.MemoryFile(tif.content) as memory, memory.open() as raster:
        data = raster.read(1)
        assert data[5, 20] == 1 and data[20, 20] == 2
    assert str(client.app.state.store.root) not in response.text
    run = result.facts["layer_urls"]["fused"].split('/')[-2]
    for private in ("result.json", "access.json", "report.html", "source.tif"):
        assert client.get(f"/artifacts/tool3/{run}/{private}").status_code == 404


def test_three_channel_rgb_rejects_without_false_maps(client, pack_c, geotiff_bytes):
    optical = client.post("/upload", files={"file": ("rgb.tif", geotiff_bytes(descriptions=["red", "green", "blue"]), "image/tiff")}).json()
    sar = client.post("/upload", files={"file": ("sar.tif", geotiff_bytes(bands=2, descriptions=["VV", "VH"], tags={"units": "linear"}), "image/tiff")}).json()
    response = execute(client, [optical["asset_id"], sar["asset_id"]])
    result = ResultEnvelope.model_validate(response.json())
    assert result.task == "reject" and result.receipt.rejected
    assert result.parameters["rejection_code"] == "tool3_invalid_dataset"
    assert "Missing required bands" in result.receipt.reason
    assert result.receipt.trace[-1].stage == "tool" and result.receipt.trace[-1].status == "rejected"
    assert result.facts == {} and result.overlay.file is None


def test_malformed_sar_units_and_dates_reject_actionably(client, pack_c):
    with rasterio.open(pack_c[1], 'r+') as raster:
        raster.set_band_unit(1, '')
        raster.set_band_unit(2, '')
    result = execute(client, attach(client, pack_c)).json()
    assert result['task'] == 'reject'
    assert 'units' in result['receipt']['reason'].lower()
    with rasterio.open(pack_c[1], 'r+') as raster:
        raster.set_band_unit(1, 'linear')
        raster.set_band_unit(2, 'linear')
        raster.update_tags(ACQUISITION_DATE='2026-03-01')
    result = execute(client, attach(client, pack_c)).json()
    assert result['task'] == 'reject' and '30 days' in result['receipt']['reason']


def test_expired_assets_invalidate_existing_map_urls(client, pack_c):
    ids = attach(client, pack_c)
    result = execute(client, ids).json()
    url = result['facts']['layer_urls']['fused']
    assert client.get(url).status_code == 200
    store = client.app.state.store
    record = store.load(UUID(ids[0]))
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    manifest = store.root / ids[0] / 'metadata.json'
    manifest.write_text(record.model_dump_json(), encoding='utf-8')
    assert client.get(url).status_code == 404


def test_worker_limit_and_retry_after_completion(client, pack_c):
    ids = attach(client, pack_c)
    slots = client.app.state.service.tool_slots
    assert slots.acquire(blocking=False)
    try:
        response = execute(client, ids)
        assert response.status_code == 429
        assert response.json()['error']['code'] == 'tool3_busy'
    finally:
        slots.release()
    assert execute(client, ids).json()['task'] == 'optical_sar'


def test_mounted_web_api_returns_urls_under_api_prefix(settings, tmp_path, pack_c):
    static = tmp_path / 'static'
    static.mkdir()
    (static / 'index.html').write_text('<html>test</html>', encoding='utf-8')
    with TestClient(create_web_app(settings, static_dir=static)) as client:
        result = execute(client, attach(client, pack_c, '/api'), '/api').json()
        assert result['task'] == 'optical_sar'
        for url in result['facts']['layer_urls'].values():
            assert url.startswith('/api/artifacts/tool3/')
            assert client.get(url).status_code == 200
