"""Tool 1: Single image land-cover analysis and visual evidence generator."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from PIL import Image
import rasterio

from satquery.contracts import (
    AssetRecord,
    Overlay,
    OverlayType,
    RoutePlan,
    ToolResult,
)
from satquery.errors import SatQueryError, ToolExecutionError
from satquery.tools.context import ToolContext

logger = logging.getLogger(__name__)

RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{32}\Z")
PUBLIC_ARTIFACTS = frozenset({"overlay.png"})

# ============================================================
# PACK A LABELS
# ============================================================
PACK_A_LABELS = [
    "water",
    "vegetation",
    "built-up",
]

# Standard band description tokens
_BAND_ROLE_PATTERNS = {
    "blue": re.compile(r"\b(blue|b02|b2|band0?2)\b", re.IGNORECASE),
    "green": re.compile(r"\b(green|grn|b03|b3|band0?3)\b", re.IGNORECASE),
    "red": re.compile(r"\b(red|b04|b4|band0?4)\b", re.IGNORECASE),
    "nir": re.compile(r"\b(nir|b08|b8|b8a|band0?8)\b", re.IGNORECASE),
}


# ============================================================
# BAND RESOLUTION
# ============================================================

def resolve_bands(
    data: np.ndarray, descriptions: list[str | None] | None = None
) -> tuple[dict[str, np.ndarray], list[str]]:
    """
    Resolves spectral band roles (green, nir, red, blue) from descriptions or band position.
    
    Returns:
        roles: mapping from role name ('green', 'nir', 'red', 'blue') to 2D numpy array.
        warnings: list of warnings generated during band resolution.
    """
    band_count = data.shape[0]
    roles: dict[str, np.ndarray] = {}
    warnings: list[str] = []

    # Try matching roles from descriptions if provided
    matched_indices: dict[str, int] = {}
    if descriptions:
        for idx, desc in enumerate(descriptions):
            if not desc or idx >= band_count:
                continue
            cleaned = desc.strip()
            for role, pattern in _BAND_ROLE_PATTERNS.items():
                if role not in matched_indices and pattern.search(cleaned):
                    matched_indices[role] = idx
                    roles[role] = data[idx]

    # Fallbacks when descriptions are missing or incomplete
    if "green" not in roles or "red" not in roles or "blue" not in roles:
        if band_count >= 4:
            # Common 4-band satellite order: Band 1=Blue, Band 2=Green, Band 3=Red, Band 4=NIR
            if "blue" not in roles:
                roles["blue"] = data[0]
            if "green" not in roles:
                roles["green"] = data[1]
            if "red" not in roles:
                roles["red"] = data[2]
            if "nir" not in roles:
                roles["nir"] = data[3]
            warnings.append(
                "Positional band order assumed (1=Blue, 2=Green, 3=Red, 4=NIR). "
                "Satellite files without tagged band names may affect spectral index accuracy."
            )
        elif band_count == 3:
            # Standard 3-band RGB: Band 1=Red, Band 2=Green, Band 3=Blue
            if "red" not in roles:
                roles["red"] = data[0]
            if "green" not in roles:
                roles["green"] = data[1]
            if "blue" not in roles:
                roles["blue"] = data[2]
            warnings.append(
                "3-band RGB image detected without NIR band. Rule-based visible detection used."
            )
        else:
            # Single-band or 2-band
            gray = data[0]
            roles["red"] = gray
            roles["green"] = gray
            roles["blue"] = gray
            warnings.append(
                f"{band_count}-band image detected. Grayscale brightness analysis used."
            )

    return roles, warnings


# ============================================================
# IMAGE LOADING (GeoTIFF + Standalone Desktop Fallback)
# ============================================================

def load_image(image_path: str | Path) -> tuple[np.ndarray, dict[str, Any], list[str | None]]:
    """
    Loads a satellite image from disk. Supports GeoTIFF and fallback PNG/JPEG.

    Returns:
        image_data: numpy array shaped (Bands, Height, Width)
        metadata: information dictionary
        descriptions: list of band descriptions
    """
    path = Path(image_path)
    extension = path.suffix.lower()

    if extension in [".tif", ".tiff"]:
        with rasterio.open(path) as src:
            data = src.read()
            descriptions = list(src.descriptions)
            metadata = {
                "width": src.width,
                "height": src.height,
                "bands": src.count,
                "dtype": str(data.dtype),
                "crs": str(src.crs),
                "transform": str(src.transform),
            }
        return data, metadata, descriptions

    elif extension in [".png", ".jpg", ".jpeg"]:
        img = Image.open(path).convert("RGB")
        data = np.array(img)
        # Convert (H, W, C) -> (C, H, W)
        data = np.transpose(data, (2, 0, 1))
        metadata = {
            "width": img.width,
            "height": img.height,
            "bands": 3,
            "dtype": str(data.dtype),
            "crs": None,
            "transform": None,
        }
        return data, metadata, [None, None, None]

    else:
        raise ValueError("Unsupported image format. Use TIFF, GeoTIFF, PNG or JPEG.")


# ============================================================
# NORMALIZE BAND
# ============================================================

def normalize_band(band: np.ndarray) -> np.ndarray:
    """Converts a band into float32 values between 0 and 1."""
    band_f = band.astype(np.float32)
    minimum = float(np.nanmin(band_f))
    maximum = float(np.nanmax(band_f))

    if maximum == minimum:
        if maximum > 0:
            scale = 255.0 if maximum <= 255.0 else maximum
            return np.clip(band_f / scale, 0.0, 1.0)
        return np.zeros_like(band_f, dtype=np.float32)

    normalized = (band_f - minimum) / (maximum - minimum)
    return np.clip(normalized, 0.0, 1.0)


# ============================================================
# NDWI WATER DETECTION
# ============================================================

def detect_water_ndwi(green: np.ndarray, nir: np.ndarray) -> tuple[np.ndarray, bool]:
    """
    Detect water using Normalized Difference Water Index (NDWI).
    NDWI = (Green - NIR) / (Green + NIR)
    """
    green_f = green.astype(np.float32)
    nir_f = nir.astype(np.float32)

    denominator = green_f + nir_f
    denominator = np.where(denominator == 0, 1e-6, denominator)

    ndwi = (green_f - nir_f) / denominator
    water_mask = ndwi > 0.20

    water_percentage = (np.sum(water_mask) / water_mask.size) * 100.0
    has_water = bool(water_percentage >= 1.0)

    return water_mask, has_water


# ============================================================
# SIMPLE WATER DETECTION FOR RGB
# ============================================================

def detect_water_rgb(
    red: np.ndarray, green: np.ndarray, blue: np.ndarray
) -> tuple[np.ndarray, bool]:
    """Fallback rule-based water detection when multispectral NIR is unavailable."""
    r = normalize_band(red)
    g = normalize_band(green)
    b = normalize_band(blue)

    water_mask = (b > r * 1.05) & (b > g * 0.95) & (b > 0.25)
    water_percentage = (np.sum(water_mask) / water_mask.size) * 100.0
    has_water = bool(water_percentage >= 2.0)

    return water_mask, has_water


# ============================================================
# BUILT-UP DETECTION
# ============================================================

def detect_built_up(
    red: np.ndarray, green: np.ndarray, blue: np.ndarray
) -> tuple[np.ndarray, bool]:
    """Brightness-based baseline built-up detection."""
    r = normalize_band(red)
    g = normalize_band(green)
    b = normalize_band(blue)

    brightness = (r + g + b) / 3.0
    built_up_mask = brightness > 0.70

    built_up_percentage = (np.sum(built_up_mask) / built_up_mask.size) * 100.0
    has_built_up = bool(built_up_percentage >= 2.0)

    return built_up_mask, has_built_up


# ============================================================
# VEGETATION DETECTION
# ============================================================

def detect_vegetation(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    nir: np.ndarray | None = None,
) -> tuple[np.ndarray, bool]:
    """
    Vegetation detection using NDVI if NIR is available, or RGB dominance otherwise.
    NDVI = (NIR - Red) / (NIR + Red)
    """
    if nir is not None:
        red_f = red.astype(np.float32)
        nir_f = nir.astype(np.float32)

        denominator = nir_f + red_f
        denominator = np.where(denominator == 0, 1e-6, denominator)

        ndvi = (nir_f - red_f) / denominator
        vegetation_mask = ndvi > 0.30
    else:
        r = normalize_band(red)
        g = normalize_band(green)
        b = normalize_band(blue)
        vegetation_mask = (g > r * 1.05) & (g > b * 1.05)

    vegetation_percentage = (np.sum(vegetation_mask) / vegetation_mask.size) * 100.0
    has_vegetation = bool(vegetation_percentage >= 5.0)

    return vegetation_mask, has_vegetation


# ============================================================
# CREATE VISUAL OVERLAY
# ============================================================

def create_overlay(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    water_mask: np.ndarray | None,
    built_up_mask: np.ndarray | None,
    vegetation_mask: np.ndarray | None,
    output_path: str | Path,
) -> None:
    """Creates a visual RGB overlay highlighting detected land-cover classes."""
    r = normalize_band(red)
    g = normalize_band(green)
    b = normalize_band(blue)

    rgb = np.stack([r, g, b], axis=2)
    rgb = (rgb * 255.0).astype(np.uint8)
    overlay = rgb.astype(np.float32)

    # Water highlighted in Blue [0, 0, 255]
    if water_mask is not None:
        overlay[water_mask] = 0.5 * overlay[water_mask] + 0.5 * np.array([0, 0, 255])

    # Built-up highlighted in Red [255, 0, 0]
    if built_up_mask is not None:
        overlay[built_up_mask] = 0.5 * overlay[built_up_mask] + 0.5 * np.array([255, 0, 0])

    # Vegetation highlighted in Green [0, 255, 0]
    if vegetation_mask is not None:
        overlay[vegetation_mask] = 0.5 * overlay[vegetation_mask] + 0.5 * np.array([0, 255, 0])

    overlay = np.clip(overlay, 0, 255).astype(np.uint8)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(overlay).save(output_path)


# ============================================================
# PACK A CHECK
# ============================================================

def is_pack_a(filename_or_path: str) -> bool:
    """Checks whether the image matches Pack A naming conventions."""
    name = os.path.basename(str(filename_or_path)).lower()
    return "pack_a" in name or "pack-a" in name


# ============================================================
# CAPTION & QUESTION ANSWERING
# ============================================================

def create_caption(labels: list[str]) -> str:
    """Formats a readable caption from detected labels."""
    if not labels or labels == ["unknown"]:
        return "This scene does not contain significant water, vegetation, or built-up features."
    return f"This scene contains: {', '.join(labels)}."


def answer_question(question: str, labels: list[str], has_water: bool) -> str:
    """Answers operator queries based on the image analysis results."""
    lower = question.lower().strip()

    if (
        "is there water" in lower
        or "is water present" in lower
        or "does the image contain water" in lower
        or "contain water" in lower
    ):
        return "yes" if has_water else "no"

    if "describe the land-cover" in lower or "major objects" in lower or "land cover" in lower:
        return create_caption(labels)

    return create_caption(labels)


# ============================================================
# CORE SPECIALIST HANDLER FOR SATQUERY ROUTER
# ============================================================

def single_image_v1(
    assets: list[AssetRecord],
    plan: RoutePlan,
    context: ToolContext | None = None,
) -> ToolResult:
    """
    Specialist handler for single-image land-cover analysis.
    Satisfies SatQuery's ToolHandler interface: (assets, plan, context) -> ToolResult.
    """
    if len(assets) != 1:
        raise ToolExecutionError(
            422,
            "tool1_invalid_assets",
            "Single image analysis requires exactly one asset.",
            as_rejection=True,
        )

    asset = assets[0]
    question = str(plan.parameters.get("question", "Describe the land cover in this scene."))
    start_time = time.time()

    # Determine file path
    if context is not None:
        source_path = context.store.source_path(asset)
    else:
        source_path = Path(asset.stored_name)

    if not source_path.exists():
        raise ToolExecutionError(
            404,
            "tool1_asset_missing",
            f"Asset raster file not found on disk: {asset.asset_id}",
        )

    # Read raster bands and metadata
    try:
        with rasterio.open(source_path) as src:
            data = src.read()
            descriptions = list(src.descriptions)
            metadata = {
                "width": src.width,
                "height": src.height,
                "bands": src.count,
                "dtype": str(data.dtype),
                "crs": str(src.crs),
                "transform": str(src.transform),
            }
    except Exception as exc:
        logger.exception("Failed to read raster for single image analysis")
        raise ToolExecutionError(
            500,
            "tool1_raster_error",
            f"Could not read uploaded raster: {exc}",
        ) from exc

    # Resolve bands
    roles, band_warnings = resolve_bands(data, descriptions)
    red = roles["red"]
    green = roles["green"]
    blue = roles["blue"]
    nir = roles.get("nir")

    # Pack A check
    pack_a = is_pack_a(asset.original_name)

    # Water detection
    if nir is not None:
        water_mask, has_water = detect_water_ndwi(green, nir)
    else:
        water_mask, has_water = detect_water_rgb(red, green, blue)

    # Built-up detection
    built_up_mask, has_built_up = detect_built_up(red, green, blue)

    # Vegetation detection
    vegetation_mask, has_vegetation = detect_vegetation(red, green, blue, nir)

    # Determine labels
    if pack_a:
        labels = PACK_A_LABELS.copy()
    else:
        labels = []
        if has_water:
            labels.append("water")
        if has_vegetation:
            labels.append("vegetation")
        if has_built_up:
            labels.append("built-up")
        if not labels:
            labels.append("unknown")

    # Generate answer and caption
    answer = answer_question(question, labels, has_water)
    caption = create_caption(labels)
    execution_time = time.time() - start_time

    # Generate and store overlay if context is provided
    overlay = Overlay(type=OverlayType.NONE, file=None)
    artifacts: dict[str, str] = {}

    if context is not None:
        run_id = uuid4().hex
        run_dir = context.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        overlay_file = run_dir / "overlay.png"
        create_overlay(
            red,
            green,
            blue,
            water_mask,
            built_up_mask,
            vegetation_mask,
            overlay_file,
        )

        # Write access control manifest
        access_path = run_dir / "access.json"
        access_path.write_text(
            json.dumps({"asset_ids": [str(asset.asset_id)]}),
            encoding="utf-8",
        )

        overlay_url = f"{context.artifact_base_url}/{run_id}/overlay.png"
        overlay = Overlay(type=OverlayType.HEATMAP, file=overlay_url)
        artifacts["overlay"] = overlay_url

    facts = {
        "summary": answer,
        "caption": {"text": caption},
        "labels": labels,
        "water": bool(has_water),
        "built_up": bool(has_built_up),
        "vegetation": bool(has_vegetation),
        "is_pack_a": pack_a,
        "artifacts": artifacts,
        "image_metadata": metadata,
        "execution_time_seconds": round(execution_time, 3),
    }

    return ToolResult(
        facts=facts,
        confidence=0.0,
        warnings=band_warnings,
        overlay=overlay,
    )


# ============================================================
# ARTIFACT ACCESS FOR API ROUTE
# ============================================================

def artifact_path(context: ToolContext, run_id: str, filename: str) -> Path:
    """Validates and returns the path to a Tool 1 public artifact."""
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise SatQueryError(404, "tool1_artifact_not_found", "Invalid run id.")

    if not isinstance(filename, str) or filename not in PUBLIC_ARTIFACTS:
        raise SatQueryError(404, "tool1_artifact_not_found", "Invalid artifact name.")

    root = context.output_dir.resolve()
    run_directory = (root / run_id).resolve()
    if not run_directory.is_dir() or run_directory.parent != root:
        raise SatQueryError(404, "tool1_artifact_not_found", "Run directory not found.")

    artifact = (run_directory / filename).resolve()
    if not artifact.is_file() or artifact.parent != run_directory:
        raise SatQueryError(404, "tool1_artifact_not_found", "Artifact file not found.")

    access_path = run_directory / "access.json"
    if not access_path.is_file():
        raise SatQueryError(404, "tool1_artifact_not_found", "Access record missing.")

    try:
        data = json.loads(access_path.read_text(encoding="utf-8"))
        asset_ids = data.get("asset_ids", [])
        if not isinstance(asset_ids, list) or not asset_ids:
            raise ValueError("Malformed access record.")
        for asset_id in asset_ids:
            # Ensures asset is loaded and unexpired
            context.store.load(UUID(asset_id))
    except (OSError, ValueError, TypeError, SatQueryError) as exc:
        raise SatQueryError(
            404,
            "tool1_artifact_not_found",
            "The artifact is unavailable or its source asset has expired.",
        ) from exc

    return artifact


# ============================================================
# LAPTOP / STANDALONE ENTRY POINT
# ============================================================

def run_single(image_path: str, question: str) -> dict[str, Any]:
    """Offline standalone execution matching the original script contract."""
    start_time = time.time()
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    data, metadata, descriptions = load_image(image_path)
    pack_a = is_pack_a(image_path)

    roles, warnings = resolve_bands(data, descriptions)
    red = roles["red"]
    green = roles["green"]
    blue = roles["blue"]
    nir = roles.get("nir")

    if nir is not None:
        water_mask, has_water = detect_water_ndwi(green, nir)
    else:
        water_mask, has_water = detect_water_rgb(red, green, blue)

    built_up_mask, has_built_up = detect_built_up(red, green, blue)
    vegetation_mask, has_vegetation = detect_vegetation(red, green, blue, nir)

    if pack_a:
        labels = PACK_A_LABELS.copy()
    else:
        labels = []
        if has_water:
            labels.append("water")
        if has_vegetation:
            labels.append("vegetation")
        if has_built_up:
            labels.append("built-up")
        if not labels:
            labels.append("unknown")

    os.makedirs("outputs", exist_ok=True)
    filename = Path(image_path).stem
    overlay_path = os.path.join("outputs", f"{filename}_overlay.png")

    create_overlay(
        red, green, blue, water_mask, built_up_mask, vegetation_mask, overlay_path
    )

    answer = answer_question(question, labels, has_water)
    caption = create_caption(labels)
    execution_time = time.time() - start_time

    return {
        "labels": labels,
        "water": bool(has_water),
        "built_up": bool(has_built_up),
        "vegetation": bool(has_vegetation),
        "answer": answer,
        "caption": caption,
        "overlay": overlay_path,
        "image_metadata": metadata,
        "execution": {
            "pack_a": pack_a,
            "execution_time_seconds": round(execution_time, 3),
        },
    }


if __name__ == "__main__":
    sample_image = "demo/packs/A/Pack_A_01.tif"
    sample_question = "Describe the land-cover and major objects visible in this image."
    if os.path.exists(sample_image):
        res = run_single(sample_image, sample_question)
        print("\nRESULT:")
        print(json.dumps(res, indent=4))
    else:
        print(f"Sample image {sample_image} not found.")
