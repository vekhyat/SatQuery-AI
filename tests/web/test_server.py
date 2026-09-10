from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from apps.api.main import Settings
from apps.web.server import MAX_PREVIEW_EDGE, MAX_SOURCE_PIXELS, create_web_app

RESULT_KEYS = {
    "task",
    "tools",
    "parameters",
    "facts",
    "answer_text",
    "confidence",
    "warnings",
    "overlay",
    "receipt",
}


def _write_geotiff(
    path: Path,
    *,
    width: int = 8,
    height: int = 6,
    bands: int = 3,
    nodata: float | None = None,
    descriptions: list[str | None] | None = None,
    data: np.ndarray | None = None,
    tiled: bool = False,
    fill: int = 40,
) -> bytes:
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": bands,
        "dtype": "uint8",
        "crs": "EPSG:4326",
        "transform": from_origin(77.0, 29.0, 0.001, 0.001),
    }
    if nodata is not None:
        profile["nodata"] = nodata
    if tiled:
        profile.update(tiled=True, blockxsize=16, blockysize=16, compress="lzw")
    with rasterio.open(path, "w", **profile) as dataset:
        if data is not None:
            for index in range(1, bands + 1):
                dataset.write(np.asarray(data[index - 1], dtype=np.uint8), index)
        else:
            for index in range(1, bands + 1):
                dataset.write(
                    np.full((height, width), fill * index, dtype=np.uint8),
                    index,
                )
        if descriptions:
            for index, description in enumerate(descriptions, start=1):
                if index <= bands and description is not None:
                    dataset.set_band_description(index, description)
    return path.read_bytes()


@pytest.fixture
def geotiff_bytes(tmp_path: Path) -> Callable[..., bytes]:
    counter = 0

    def make(**kwargs: Any) -> bytes:
        nonlocal counter
        counter += 1
        return _write_geotiff(tmp_path / f"scene-{counter}.tif", **kwargs)

    return make


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        runtime_dir=tmp_path / "runtime" / "uploads",
        max_upload_bytes=4 * 1024 * 1024,
        retention_hours=24,
    )


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "static"
    directory.mkdir()
    (directory / "index.html").write_text(
        "<!doctype html><title>SatQuery</title><p>investigation notebook</p>",
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def client(settings: Settings, static_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_web_app(settings, static_dir=static_dir)) as test_client:
        yield test_client


def upload(
    client: TestClient,
    content: bytes,
    *,
    name: str = "scene.tif",
    modality: str = "optical",
):
    return client.post(
        "/api/upload",
        files={"file": (name, content, "image/tiff")},
        data={"modality": modality},
    )


def png_ihdr(data: bytes) -> tuple[int, int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    length, tag = struct.unpack(">I4s", data[8:16])
    assert tag == b"IHDR" and length == 13
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, color_type


def png_rgba(data: bytes) -> tuple[int, int, bytes]:
    width, height, color_type = png_ihdr(data)
    assert color_type == 6
    offset = 8
    idat = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        tag = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        if tag == b"IDAT":
            idat.extend(chunk)
        elif tag == b"IEND":
            break
        offset += 12 + length
    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    pixels = bytearray()
    cursor = 0
    for _ in range(height):
        assert raw[cursor] == 0
        cursor += 1
        pixels.extend(raw[cursor : cursor + stride])
        cursor += stride
    return width, height, bytes(pixels)


def test_root_content_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "SatQuery" in response.text
    assert "investigation notebook" in response.text


def test_health_upload_query_runs_tool1_specialist_analysis(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert "runtime" not in health.text.lower()

    uploaded = upload(client, geotiff_bytes(descriptions=["red", "green", "blue"]))
    assert uploaded.status_code == 201
    asset_id = uploaded.json()["asset_id"]

    queried = client.post(
        "/api/query",
        json={"asset_ids": [asset_id], "question": "Describe the land cover"},
    )
    assert queried.status_code == 200
    result = queried.json()
    assert set(result) == RESULT_KEYS
    assert result["task"] == "single_image"
    assert result["confidence"] == 0.0
    assert isinstance(result["facts"], dict)
    assert "summary" in result["facts"]
    assert result["overlay"]["type"] == "heatmap"
    assert isinstance(result["overlay"]["file"], str)
    assert result["overlay"]["file"].startswith("/api/artifacts/tool1/")
    assert "This scene" in result["answer_text"]
    assert result["receipt"]["trace"][-1]["status"] == "ok"
    assert "single_image_v1" in result["tools"]
    assert result["facts"]["confidence_status"] == "not_measured"


def test_preview_returns_bounded_png(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    content = geotiff_bytes(
        width=800,
        height=400,
        descriptions=["red", "green", "blue"],
    )
    asset_id = upload(client, content).json()["asset_id"]
    response = client.get(f"/api/preview/{asset_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "private,max-age=300"
    width, height, color_type = png_ihdr(response.content)
    assert color_type == 6
    assert max(width, height) <= MAX_PREVIEW_EDGE
    assert width == MAX_PREVIEW_EDGE
    assert height == 384


def test_preview_expired_id_is_404(
    client: TestClient,
    settings: Settings,
    geotiff_bytes: Callable[..., bytes],
) -> None:
    asset_id = upload(client, geotiff_bytes()).json()["asset_id"]
    manifest = settings.runtime_dir / asset_id / "metadata.json"
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    manifest.write_text(json.dumps(record), encoding="utf-8")
    response = client.get(f"/api/preview/{asset_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset_not_found"


def test_preview_nodata_is_valid_png(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    data = np.full((3, 6, 8), 80, dtype=np.uint8)
    data[:, 0, 0] = 0
    content = geotiff_bytes(nodata=0, data=data, descriptions=["red", "green", "blue"])
    asset_id = upload(client, content).json()["asset_id"]
    response = client.get(f"/api/preview/{asset_id}")
    assert response.status_code == 200
    width, height, pixels = png_rgba(response.content)
    assert (width, height) == (8, 6)
    assert pixels[3] == 0
    assert pixels[7] == 255


def test_preview_malformed_uuid_is_422(client: TestClient) -> None:
    response = client.get("/api/preview/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_preview_unavailable_keeps_query_valid(
    client: TestClient,
    geotiff_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.web.server.MAX_SOURCE_PIXELS", 10)
    asset_id = upload(client, geotiff_bytes()).json()["asset_id"]
    preview = client.get(f"/api/preview/{asset_id}")
    assert preview.status_code == 422
    error = preview.json()["error"]
    assert error["code"] == "preview_unavailable"
    assert "validated file can still be queried" in error["message"]
    queried = client.post(
        "/api/query",
        json={"asset_ids": [asset_id], "question": "Describe this scene"},
    )
    assert queried.status_code == 200
    assert queried.json()["task"] == "single_image"


def test_source_pixel_budget_limit() -> None:
    assert 10_000 * 10_000 <= MAX_SOURCE_PIXELS
    assert 10_001 * 10_000 > MAX_SOURCE_PIXELS
