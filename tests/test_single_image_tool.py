"""Tests for Tool 1 (Single image land-cover analysis)."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from threading import BoundedSemaphore
from uuid import uuid4

import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.transform import from_origin

from satquery.checker import inspect_raster
from satquery.contracts import AssetRecord, ModalityHint, OverlayType, RoutePlan, Task
from satquery.errors import SatQueryError, ToolExecutionError
from satquery.storage import AssetStore, PendingAsset
from satquery.tools.context import ToolContext, build_tool_context
from satquery.tools.pack_a import create_pack_a
from satquery.tools.single_image import (
    PACK_A_LABELS,
    answer_question,
    artifact_path,
    create_overlay,
    detect_built_up,
    detect_vegetation,
    detect_water_ndwi,
    is_pack_a,
    load_image,
    resolve_bands,
    run_single,
    single_image_v1,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_PACK_A = REPO_ROOT / "demo" / "packs" / "A" / "Pack_A_01.tif"


def _write_geotiff(
    path: Path,
    bands: list[np.ndarray],
    descriptions: list[str | None] | None = None,
) -> Path:
    first = np.asarray(bands[0])
    height, width = first.shape
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": len(bands),
        "dtype": "uint8",
        "crs": "EPSG:4326",
        "transform": from_origin(77.0, 29.0, 0.001, 0.001),
    }
    with rasterio.open(path, "w", **profile) as dataset:
        for index, band in enumerate(bands, start=1):
            dataset.write(np.asarray(band, dtype=np.uint8), index)
            if descriptions and index <= len(descriptions) and descriptions[index - 1] is not None:
                dataset.set_band_description(index, descriptions[index - 1])
    return path


def _prepare_tool1_run(
    tmp_path: Path,
    raster_path: Path,
    *,
    original_name: str | None = None,
) -> tuple[AssetRecord, ToolContext, RoutePlan]:
    store = AssetStore(tmp_path / "uploads", 2_000_000, timedelta(hours=1))
    asset_id = uuid4()
    directory = store.root / str(asset_id)
    directory.mkdir()
    stored = directory / "source.tif"
    stored.write_bytes(raster_path.read_bytes())
    metadata, warnings = inspect_raster(stored, modality_hint=ModalityHint.OPTICAL)
    pending = PendingAsset(
        asset_id=asset_id,
        original_name=original_name or raster_path.name,
        stored_name="source.tif",
        path=stored,
        size_bytes=stored.stat().st_size,
        sha256=hashlib.sha256(stored.read_bytes()).hexdigest(),
    )
    asset = store.finalize(pending, metadata, warnings)
    context = build_tool_context(
        task=Task.SINGLE_IMAGE,
        store=store,
        artifact_root_url="/artifacts",
        slots=BoundedSemaphore(1),
    )
    plan = RoutePlan(
        task=Task.SINGLE_IMAGE,
        tool="single_image_v1",
        ordered_asset_ids=[asset.asset_id],
        parameters={"question": "Describe the land cover"},
        why="test",
    )
    return asset, context, plan


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


def test_rgb_tagged_unlabeled_fourth_band_is_nir(tmp_path, monkeypatch):
    data = np.zeros((4, 8, 8), dtype=np.uint8)
    data[0] = 10
    data[1] = 20
    data[2] = 30
    data[3] = 40
    roles, warnings = resolve_bands(data, ["red", "green", "blue", None])
    assert np.array_equal(roles["red"], data[0])
    assert np.array_equal(roles["green"], data[1])
    assert np.array_equal(roles["blue"], data[2])
    assert np.array_equal(roles["nir"], data[3])
    assert all("3-band RGB" not in warning for warning in warnings)

    monkeypatch.chdir(tmp_path)
    height = width = 16
    red = np.full((height, width), 130, dtype=np.uint8)
    green = np.full((height, width), 140, dtype=np.uint8)
    blue = np.full((height, width), 120, dtype=np.uint8)
    nir = np.full((height, width), 10, dtype=np.uint8)
    path = _write_geotiff(
        tmp_path / "rgb_plus_unlabeled.tif",
        [red, green, blue, nir],
        ["red", "green", "blue", None],
    )
    with rasterio.open(path) as src:
        loaded = src.read()
        descriptions = list(src.descriptions)
    file_roles, _ = resolve_bands(loaded, descriptions)
    assert np.array_equal(file_roles["nir"], loaded[3])
    result = run_single(str(path), "Is there water present?")
    assert result["water"] is True


def test_is_pack_a():
    assert is_pack_a("Pack_A_01.tif") is True
    assert is_pack_a("path/to/my-pack-a.tiff") is True
    assert is_pack_a("scene_01.tif") is False
    assert is_pack_a("pack-alert.tif") is False
    assert is_pack_a("pack_archive.tif") is False
    assert is_pack_a("dispatch-pack-assignment.tif") is False


def test_answer_question():
    labels = ["water", "vegetation"]
    assert answer_question("Is there water present?", labels, has_water=True) == "yes"
    assert answer_question("Is there any water?", labels, has_water=True) == "yes"
    assert answer_question("Does this contain water?", labels, has_water=False) == "no"
    assert "water" in answer_question("Describe the land cover", labels, has_water=True)
    describe = answer_question(
        "Describe the land cover and whether it contains water",
        labels,
        has_water=True,
    )
    assert describe != "yes"
    assert "water" in describe


def test_standalone_run_single_on_png(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    png_path = tmp_path / "test_image.png"
    img = Image.new("RGB", (32, 32), color=(0, 200, 0))  # Green
    img.save(png_path)

    result = run_single(str(png_path), "Describe the land cover")
    assert "labels" in result
    assert "caption" in result
    assert "overlay" in result
    assert Path(result["overlay"]).exists()


def test_pack_a_filename_does_not_override_empty_detections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    empty = np.full((16, 16), 80, dtype=np.uint8)
    path = _write_geotiff(
        tmp_path / "Pack_A_01.tif",
        [empty, empty, empty, empty],
        ["blue", "green", "red", "nir"],
    )
    standalone = run_single(str(path), "Describe the land cover")
    assert standalone["labels"] != PACK_A_LABELS
    assert "water" not in standalone["labels"]
    assert "vegetation" not in standalone["labels"]
    assert "built-up" not in standalone["labels"]
    assert standalone["water"] is False
    assert standalone["vegetation"] is False
    assert standalone["built_up"] is False
    assert is_pack_a(path.name) is True

    asset, context, plan = _prepare_tool1_run(tmp_path / "ctx", path, original_name="Pack_A_01.tif")
    result = single_image_v1([asset], plan, context)
    assert result.facts["is_pack_a"] is True
    assert result.facts["labels"] != PACK_A_LABELS
    assert result.facts["water"] is False
    assert result.facts["vegetation"] is False
    assert result.facts["built_up"] is False
    assert "water" not in result.facts["labels"]
    assert "vegetation" not in result.facts["labels"]
    assert "built-up" not in result.facts["labels"]


def test_create_pack_a_detects_water_vegetation_and_built_up(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "Pack_A_01.tif"
    if DEMO_PACK_A.is_file():
        source.write_bytes(DEMO_PACK_A.read_bytes())
    else:
        create_pack_a(source)

    result = run_single(str(source), "Describe the land cover")
    assert result["water"] is True
    assert result["vegetation"] is True
    assert result["built_up"] is True
    assert "water" in result["labels"]
    assert "vegetation" in result["labels"]
    assert "built-up" in result["labels"]

    asset, context, plan = _prepare_tool1_run(tmp_path / "ctx", source, original_name="Pack_A_01.tif")
    tool_result = single_image_v1([asset], plan, context)
    assert tool_result.facts["water"] is True
    assert tool_result.facts["vegetation"] is True
    assert tool_result.facts["built_up"] is True


def test_run_single_writes_overlay_next_to_source_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "images"
    source = source_dir / "scene.tif"
    gray = np.full((8, 8), 80, dtype=np.uint8)
    _write_geotiff(source, [gray, gray, gray], ["red", "green", "blue"])

    result = run_single(str(source), "Describe the land cover")
    overlay = Path(result["overlay"]).resolve()
    assert overlay.parent == source_dir.resolve()
    assert overlay.name == "scene_overlay.png"
    assert overlay.is_file()
    assert not (tmp_path / "outputs" / "scene_overlay.png").exists()


def test_overlay_masks_match_has_star_gates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    height = width = 32
    red = np.full((height, width), 80, dtype=np.uint8)
    green = np.full((height, width), 80, dtype=np.uint8)
    blue = np.full((height, width), 80, dtype=np.uint8)
    nir = np.full((height, width), 80, dtype=np.uint8)
    # One NDWI-positive pixel is below the 1% water area gate.
    red[0, 0] = 100
    green[0, 0] = 180
    blue[0, 0] = 90
    nir[0, 0] = 10
    path = _write_geotiff(
        tmp_path / "sparse_water.tif",
        [red, green, blue, nir],
        ["red", "green", "blue", "nir"],
    )

    result = run_single(str(path), "Describe the land cover")
    assert result["water"] is False
    assert result["built_up"] is False
    assert result["vegetation"] is False
    assert "water" not in result["labels"]

    data, _metadata, descriptions = load_image(path)
    roles, _ = resolve_bands(data, descriptions)
    water_mask, has_water = detect_water_ndwi(roles["green"], roles["nir"])
    vegetation_mask, has_vegetation = detect_vegetation(
        roles["red"], roles["green"], roles["blue"], roles.get("nir")
    )
    built_up_mask, has_built_up = detect_built_up(roles["red"], roles["green"], roles["blue"])
    assert has_water is False and has_vegetation is False and has_built_up is False
    assert bool(np.any(water_mask)) is True

    gated_path = tmp_path / "gated_overlay.png"
    create_overlay(
        roles["red"],
        roles["green"],
        roles["blue"],
        water_mask if has_water else None,
        built_up_mask if has_built_up else None,
        vegetation_mask if has_vegetation else None,
        gated_path,
    )
    actual = np.array(Image.open(result["overlay"]))
    expected = np.array(Image.open(gated_path))
    assert np.array_equal(actual, expected)


def test_built_up_excludes_water_and_vegetation_before_area_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    height = width = 32
    red = np.full((height, width), 10, dtype=np.uint8)
    green = np.full((height, width), 10, dtype=np.uint8)
    blue = np.full((height, width), 10, dtype=np.uint8)
    nir = np.full((height, width), 10, dtype=np.uint8)
    # Left half: bright water (high visible, low NIR) that would pass brightness if not excluded.
    red[:, :16] = 250
    green[:, :16] = 250
    blue[:, :16] = 250
    nir[:, :16] = 5
    # Right-center: vegetation (high NIR, low red) covering the remaining non-dark pixels.
    red[:, 16:28] = 40
    green[:, 16:28] = 200
    blue[:, 16:28] = 40
    nir[:, 16:28] = 220
    path = _write_geotiff(
        tmp_path / "water_and_veg.tif",
        [red, green, blue, nir],
        ["red", "green", "blue", "nir"],
    )

    result = run_single(str(path), "Describe the land cover")
    assert result["water"] is True
    assert result["vegetation"] is True
    assert result["built_up"] is False
    assert "built-up" not in result["labels"]


def test_single_image_v1_writes_overlay_under_tool_context(tmp_path):
    gray = np.full((8, 8), 80, dtype=np.uint8)
    path = _write_geotiff(tmp_path / "scene.tif", [gray, gray, gray], ["red", "green", "blue"])
    asset, context, plan = _prepare_tool1_run(tmp_path, path)

    result = single_image_v1([asset], plan, context)

    assert result.overlay.type == OverlayType.HEATMAP
    assert isinstance(result.overlay.file, str)
    prefix = context.artifact_base_url.rstrip("/") + "/"
    assert result.overlay.file.startswith(prefix)
    assert result.overlay.file.endswith("/overlay.png")
    run_id = result.overlay.file[len(prefix) :].split("/", 1)[0]
    run_dir = context.output_dir / run_id
    assert (run_dir / "overlay.png").is_file()
    access_path = run_dir / "access.json"
    assert access_path.is_file()
    access = json.loads(access_path.read_text(encoding="utf-8"))
    assert str(asset.asset_id) in [str(item) for item in access["asset_ids"]]
    resolved = artifact_path(context, run_id, "overlay.png")
    assert resolved == (run_dir / "overlay.png").resolve()
    assert result.confidence == 0.0
    assert result.facts["confidence_status"] == "not_measured"


def test_single_image_v1_without_context_raises_missing_tool_context(tmp_path):
    gray = np.full((8, 8), 80, dtype=np.uint8)
    path = _write_geotiff(tmp_path / "scene.tif", [gray, gray, gray], ["red", "green", "blue"])
    asset, _context, plan = _prepare_tool1_run(tmp_path, path)

    with pytest.raises(ToolExecutionError) as caught:
        single_image_v1([asset], plan, None)

    assert caught.value.status_code == 500
    assert caught.value.code == "missing_tool_context"
    assert caught.value.as_rejection is False


@pytest.mark.parametrize(
    ("run_id", "filename"),
    (
        ("c" * 32, "../overlay.png"),
        ("c" * 32, "..\\overlay.png"),
        ("c" * 32, "access.json"),
        ("c" * 32, "unexpected.png"),
        ("c" * 32, "nested/overlay.png"),
        ("../" + "c" * 32, "overlay.png"),
    ),
)
def test_artifact_path_rejects_traversal_and_unknown_filenames(tmp_path, run_id, filename):
    store = AssetStore(tmp_path / "uploads", 1024, timedelta(hours=1))
    context = build_tool_context(
        task=Task.SINGLE_IMAGE,
        store=store,
        artifact_root_url="/artifacts",
        slots=BoundedSemaphore(1),
    )

    with pytest.raises(SatQueryError) as caught:
        artifact_path(context, run_id, filename)

    assert caught.value.status_code == 404
    assert caught.value.code == "tool1_artifact_not_found"
    assert str(tmp_path) not in caught.value.message
    assert "C:\\Users" not in caught.value.message


def test_spaced_band_descriptions_map_sentinel_roles():
    data = np.zeros((4, 6, 6), dtype=np.uint8)
    data[0] = 11
    data[1] = 22
    data[2] = 33
    data[3] = 44
    roles, warnings = resolve_bands(data, ["Band 2", "Band 3", "Band 4", "Band 8"])
    assert np.array_equal(roles["blue"], data[0])
    assert np.array_equal(roles["green"], data[1])
    assert np.array_equal(roles["red"], data[2])
    assert np.array_equal(roles["nir"], data[3])
    assert warnings == []


def test_two_band_green_nir_does_not_overwrite_green():
    data = np.zeros((2, 8, 8), dtype=np.uint8)
    data[0] = 140
    data[1] = 10
    roles, _warnings = resolve_bands(data, ["green", "nir"])
    assert np.array_equal(roles["green"], data[0])
    assert np.array_equal(roles["nir"], data[1])
    mask, has_water = detect_water_ndwi(roles["green"], roles["nir"])
    assert has_water is True
    assert np.all(mask)


def test_nodata_fill_is_not_classified_as_water(tmp_path):
    height = width = 20
    green = np.full((height, width), 30, dtype=np.int16)
    nir = np.full((height, width), 180, dtype=np.int16)
    green[:10, :] = -9999
    nir[:10, :] = -9999
    path = tmp_path / "nodata.tif"
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 2,
        "dtype": "int16",
        "nodata": -9999,
        "crs": "EPSG:4326",
        "transform": from_origin(77.0, 29.0, 0.001, 0.001),
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(green, 1)
        dataset.write(nir, 2)
        dataset.set_band_description(1, "green")
        dataset.set_band_description(2, "nir")

    data, _metadata, descriptions = load_image(path)
    roles, _ = resolve_bands(data, descriptions)
    _mask, has_water = detect_water_ndwi(roles["green"], roles["nir"])
    assert has_water is False
