from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from rasterio.transform import Affine

from apps.api.main import Settings, create_app
from tests.test_api import upload


def test_non_tiff_extension_is_415_and_creates_no_asset(
    client: TestClient, geotiff_bytes: Callable[..., bytes], settings: Settings
) -> None:
    response = upload(client, geotiff_bytes(), name="scene.png")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert not any(settings.runtime_dir.iterdir())


def test_disguised_corrupt_tiff_is_422_and_partial_file_is_removed(
    client: TestClient, settings: Settings
) -> None:
    response = upload(client, b"this is not a raster", name="fake.tif")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "corrupt_geotiff"
    assert not any(settings.runtime_dir.iterdir())


def test_missing_crs_and_identity_transform_are_422(
    client: TestClient,
    geotiff_bytes: Callable[..., bytes],
    settings: Settings,
) -> None:
    missing_crs = upload(client, geotiff_bytes(crs=None))
    assert missing_crs.status_code == 422
    assert missing_crs.json()["error"]["code"] == "missing_crs"

    identity = upload(client, geotiff_bytes(transform=Affine.identity()))
    assert identity.status_code == 422
    assert identity.json()["error"]["code"] == "invalid_transform"
    assert not any(settings.runtime_dir.iterdir())


def test_invalid_date_is_422_without_storing_file(
    client: TestClient,
    geotiff_bytes: Callable[..., bytes],
    settings: Settings,
) -> None:
    response = upload(client, geotiff_bytes(), acquisition_date="not-a-date")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"
    assert not any(settings.runtime_dir.iterdir())


def test_oversized_upload_is_413_and_partial_file_is_removed(
    tmp_path: Path, geotiff_bytes: Callable[..., bytes]
) -> None:
    settings = Settings(
        runtime_dir=tmp_path / "small-runtime",
        max_upload_bytes=10,
        retention_hours=24,
    )
    with TestClient(create_app(settings)) as client:
        response = upload(client, geotiff_bytes())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert not any(settings.runtime_dir.iterdir())
