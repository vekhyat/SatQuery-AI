from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import Affine, from_origin

from apps.api.main import Settings, create_app


@pytest.fixture
def geotiff_bytes(tmp_path: Path) -> Callable[..., bytes]:
    counter = 0

    def make(
        *,
        bands: int = 3,
        crs: str | None = "EPSG:4326",
        transform: Affine | None = None,
        tags: dict[str, str] | None = None,
        descriptions: list[str | None] | None = None,
    ) -> bytes:
        nonlocal counter
        counter += 1
        path = tmp_path / f"fixture-{counter}.tif"
        raster_transform = transform or from_origin(77.0, 29.0, 0.001, 0.001)
        profile = {
            "driver": "GTiff",
            "width": 8,
            "height": 6,
            "count": bands,
            "dtype": "uint8",
            "transform": raster_transform,
        }
        if crs is not None:
            profile["crs"] = crs
        with rasterio.open(path, "w", **profile) as dataset:
            for index in range(1, bands + 1):
                dataset.write(np.full((6, 8), index * 20, dtype=np.uint8), index)
            if tags:
                dataset.update_tags(**tags)
            if descriptions:
                for index, description in enumerate(descriptions, start=1):
                    if index <= bands and description is not None:
                        dataset.set_band_description(index, description)
        return path.read_bytes()

    return make


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        runtime_dir=tmp_path / "runtime" / "uploads",
        max_upload_bytes=2 * 1024 * 1024,
        retention_hours=24,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
