"""Tests for Tool 1 (Single image land-cover analysis)."""
from __future__ import annotations

import io
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.transform import from_origin

from satquery.contracts import AssetRecord, Modality, OverlayType, RoutePlan, Task
from satquery.tools.single_image import (
    PACK_A_LABELS,
    answer_question,
    create_overlay,
    detect_built_up,
    detect_vegetation,
    detect_water_ndwi,
    detect_water_rgb,
    is_pack_a,
    resolve_bands,
    run_single,
    single_image_v1,
)


def test_detect_water_ndwi_does_not_crash_and_detects_water():
    # Green high, NIR low -> NDWI > 0.20
    green = np.full((10, 10), 140, dtype=np.uint8)
    nir = np.full((10, 10), 10, dtype=np.uint8)

    mask, has_water = detect_water_ndwi(green, nir)
    assert has_water is True
    assert mask is not None
    assert np.all(mask)

    # Green low, NIR high -> NDWI < 0.20
    green_low = np.full((10, 10), 30, dtype=np.uint8)
    nir_high = np.full((10, 10), 180, dtype=np.uint8)
    _, has_water_neg = detect_water_ndwi(green_low, nir_high)
    assert has_water_neg is False


def test_detect_vegetation_ndvi_and_fallback():
    # NIR high, Red low -> NDVI > 0.30
    red = np.full((10, 10), 30, dtype=np.uint8)
    nir = np.full((10, 10), 180, dtype=np.uint8)
    _, has_veg = detect_vegetation(red, np.full((10, 10), 50), np.full((10, 10), 50), nir)
    assert has_veg is True

    # Fallback RGB without NIR
    r = np.full((10, 10), 30, dtype=np.uint8)
    g = np.full((10, 10), 200, dtype=np.uint8)
    b = np.full((10, 10), 30, dtype=np.uint8)
    _, has_veg_rgb = detect_vegetation(r, g, b, nir=None)
    assert has_veg_rgb is True


def test_detect_built_up_brightness():
    # High brightness in RGB -> built-up
    r = np.full((10, 10), 220, dtype=np.uint8)
    g = np.full((10, 10), 220, dtype=np.uint8)
    b = np.full((10, 10), 220, dtype=np.uint8)
    _, has_built = detect_built_up(r, g, b)
    assert has_built is True

    # Low brightness -> not built-up
    r_dark = np.full((10, 10), 40, dtype=np.uint8)
    g_dark = np.full((10, 10), 40, dtype=np.uint8)
    b_dark = np.full((10, 10), 40, dtype=np.uint8)
    _, has_built_dark = detect_built_up(r_dark, g_dark, b_dark)
    assert has_built_dark is False


def test_band_resolution_by_names():
    # Create 4 bands in atypical order: NIR, Red, Green, Blue
    data = np.zeros((4, 10, 10), dtype=np.uint8)
    data[0] = 10  # NIR
    data[1] = 20  # Red
    data[2] = 30  # Green
    data[3] = 40  # Blue

    descriptions = ["nir", "red", "green", "blue"]
    roles, warnings = resolve_bands(data, descriptions)

    assert len(warnings) == 0
    assert np.array_equal(roles["nir"], data[0])
    assert np.array_equal(roles["red"], data[1])
    assert np.array_equal(roles["green"], data[2])
    assert np.array_equal(roles["blue"], data[3])


def test_band_resolution_fallback_warns():
    data = np.zeros((4, 10, 10), dtype=np.uint8)
    roles, warnings = resolve_bands(data, [None, None, None, None])

    assert len(warnings) == 1
    assert "Positional band order assumed" in warnings[0]
    assert np.array_equal(roles["blue"], data[0])
    assert np.array_equal(roles["green"], data[1])
    assert np.array_equal(roles["red"], data[2])
    assert np.array_equal(roles["nir"], data[3])


def test_is_pack_a():
    assert is_pack_a("Pack_A_01.tif") is True
    assert is_pack_a("path/to/my-pack-a.tiff") is True
    assert is_pack_a("scene_01.tif") is False


def test_answer_question():
    labels = ["water", "vegetation"]
    assert answer_question("Is there water present?", labels, has_water=True) == "yes"
    assert answer_question("Does this contain water?", labels, has_water=False) == "no"
    assert "water" in answer_question("Describe the land cover", labels, has_water=True)


def test_standalone_run_single_on_png(tmp_path):
    png_path = tmp_path / "test_image.png"
    img = Image.new("RGB", (32, 32), color=(0, 200, 0))  # Green
    img.save(png_path)

    result = run_single(str(png_path), "Describe the land cover")
    assert "labels" in result
    assert "caption" in result
    assert "overlay" in result
    assert Path(result["overlay"]).exists()
