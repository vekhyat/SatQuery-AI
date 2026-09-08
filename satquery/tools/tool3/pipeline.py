"""A reproducible, inspectable baseline; no trained model or accuracy claims."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import platform
from pathlib import Path
import tempfile
import threading
import time
import uuid

import cv2 as cv
import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from .inputs import DatasetError, finite_number, inspect_source, quality_valid, read_aligned, resolve_sar_units, validate_mapping
from ._version import __version__

_LATEST_LOCK = threading.Lock()


def publish_latest(temporary, destination):
    """Serialize local pointer updates and retry transient Windows sharing locks."""
    with _LATEST_LOCK:
        for attempt in range(8):
            try:
                temporary.replace(destination)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(.02 * 2 ** attempt, .16))


def publish_run(stage, destination):
    """Keep complete runs atomic while tolerating temporary Windows file locks."""
    for attempt in range(8):
        try:
            stage.rename(destination)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(.02 * 2 ** attempt, .16))


@dataclass(frozen=True)
class Config:
    sar_units: str = "auto"
    ndwi_threshold: float = 0.0
    ndbi_threshold: float = 0.0
    vegetation_threshold: float = 0.3
    sar_water_vv_db: float | None = None
    sar_water_vh_db: float | None = None
    sar_built_vv_db: float | None = None
    sar_built_vh_db: float | None = None
    speckle_size: int = 3
    morphology_size: int = 3
    min_component_pixels: int = 9
    min_component_m2: float | None = None
    min_overlap: float = 0.5
    max_date_gap_days: int = 30
    max_pixels: int = 16_000_000

    def __post_init__(self):
        if not isinstance(self.sar_units, str) or self.sar_units not in {"auto", "linear", "db"}:
            raise DatasetError("sar_units must be auto, linear, or db.")
        for name in ("ndwi_threshold", "ndbi_threshold", "vegetation_threshold"):
            value = getattr(self, name)
            if not finite_number(value) or not -1 <= value <= 1:
                raise DatasetError(f"{name} must be a finite value between -1 and 1.")
        for name in ("sar_water_vv_db", "sar_water_vh_db", "sar_built_vv_db", "sar_built_vh_db", "min_component_m2"):
            value = getattr(self, name)
            if value is not None and not finite_number(value):
                raise DatasetError(f"{name} must be finite.")
        if self.min_component_m2 is not None and self.min_component_m2 < 0:
            raise DatasetError("min_component_m2 must be nonnegative.")
        for name in ("speckle_size", "morphology_size"):
            value = getattr(self, name)
            if type(value) is not int or value < 1 or value > 31 or value % 2 == 0:
                raise DatasetError(f"{name} must be an odd integer from 1 through 31; 1 disables filtering.")
        for name, minimum in (("min_component_pixels", 0), ("max_date_gap_days", 0), ("max_pixels", 1)):
            if type(getattr(self, name)) is not int or getattr(self, name) < minimum:
                raise DatasetError(f"{name} must be an integer >= {minimum}.")
        if not finite_number(self.min_overlap) or not 0 < self.min_overlap <= 1:
            raise DatasetError("min_overlap must be greater than zero and at most one.")


def normalized_difference(a, b):
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    with np.errstate(over="ignore", invalid="ignore"):
        total = a + b
    valid = np.isfinite(a) & np.isfinite(b) & np.isfinite(total) & (total > 1e-12)
    output = np.full(a.shape, np.nan, dtype=np.float32)
    np.divide(a - b, total, out=output, where=valid)
    # Negative corrected reflectance can yield ratios outside the index domain.
    output[(output < -1) | (output > 1)] = np.nan
    return output


def clean_mask(mask, valid, size=3, minimum=9):
    image = (mask & valid).astype(np.uint8)
    if minimum > image.size:
        return np.zeros(image.shape, dtype=bool)
    if size > 1:
        kernel = np.ones((size, size), np.uint8)
        image = cv.morphologyEx(image, cv.MORPH_OPEN, kernel, borderType=cv.BORDER_CONSTANT, borderValue=0)
        image[~valid] = 0
        image = cv.morphologyEx(image, cv.MORPH_CLOSE, kernel, borderType=cv.BORDER_CONSTANT, borderValue=0)
        image[~valid] = 0
    if minimum > 1:
        count, labels, stats, _ = cv.connectedComponentsWithStats(image, connectivity=8)
        keep = np.zeros(count, dtype=bool)
        keep[1:] = stats[1:, cv.CC_STAT_AREA] >= minimum
        image = keep[labels]
    return image.astype(bool) & valid


def smooth_power(data, valid, size):
    if size == 1:
        return np.where(valid, data, np.nan)
    numerator = cv.boxFilter(np.where(valid, data, 0).astype(np.float32), -1, (size, size),
                             normalize=False, borderType=cv.BORDER_CONSTANT)
    denominator = cv.boxFilter(valid.astype(np.float32), -1, (size, size),
                               normalize=False, borderType=cv.BORDER_CONSTANT)
    result = np.full(data.shape, np.nan, dtype=np.float32)
    np.divide(numerator, denominator, out=result, where=valid & (denominator > 0))
    return result


def classify_sar(bands, config, minimum, warnings):
    valid = np.isfinite(bands["vv"]) & (bands["vv"] > 0)
    if "vh" in bands:
        valid &= np.isfinite(bands["vh"]) & (bands["vh"] > 0)
    else:
        warnings.append("VH is absent; SAR uses VV only and has less polarization evidence.")
    if not valid.any():
        raise DatasetError("SAR has no valid positive power pixels after alignment/calibration.")
    db = {}
    thresholds = {}
    water = valid.copy()
    built = valid.copy()
    for role in ("vv", "vh"):
        if role not in bands:
            continue
        power = smooth_power(bands[role], valid, config.speckle_size)
        values = np.full(power.shape, np.nan, dtype=np.float32)
        values[valid] = 10 * np.log10(power[valid])
        db[role] = values
        samples = values[valid]
        if np.ptp(samples) < 0.1:
            warnings.append(f"{role.upper()} has almost no dynamic range; verify the input and any detections.")
        water_limit = getattr(config, f"sar_water_{role}_db")
        built_limit = getattr(config, f"sar_built_{role}_db")
        # Percentiles alone force detections even on dry/empty scenes. Absolute guards
        # constrain this baseline. They are configurable and are not universal physics.
        if water_limit is None:
            water_limit = min(float(np.percentile(samples, 15 if role == "vv" else 20)), -17 if role == "vv" else -23)
        if built_limit is None:
            built_limit = max(float(np.percentile(samples, 80 if role == "vv" else 70)), -8 if role == "vv" else -15)
        if water_limit >= built_limit:
            raise DatasetError(f"{role.upper()} water threshold must be lower than its built-up threshold.")
        thresholds[f"water_{role}_db"] = float(water_limit)
        thresholds[f"built_{role}_db"] = float(built_limit)
        water &= values <= water_limit
        built &= values >= built_limit
    water = clean_mask(water, valid, config.morphology_size, minimum)
    built = clean_mask(built, valid & ~water, config.morphology_size, minimum)
    return water, built, valid, db, thresholds


def classify_optical(bands, config, minimum, warnings, raw_valid=None):
    ndwi = normalized_difference(bands["green"], bands["nir"])
    ndbi = normalized_difference(bands["swir"], bands["nir"])
    valid = np.isfinite(ndwi) & np.isfinite(ndbi)
    raw_valid = valid.copy() if raw_valid is None else raw_valid
    if not raw_valid.any():
        raise DatasetError("Optical bands have no jointly valid index pixels. Check band mapping, nodata, and scale/offset.")
    quality_excluded = np.zeros(valid.shape, dtype=bool)
    if "scl" in bands:
        clear = quality_valid(bands["scl"], "scl")
        quality_excluded |= raw_valid & ~clear
        valid &= clear
    if "valid_mask" in bands:
        clear = quality_valid(bands["valid_mask"], "valid_mask")
        quality_excluded |= raw_valid & ~clear
        valid &= clear
    if "scl" not in bands and "valid_mask" not in bands:
        warnings.append("No optical quality/cloud mask supplied; clouds, shadows, and snow may produce false detections. No under-cloud claim is made.")
    if not valid.any():
        warnings.append("No clear optical pixels remain after quality masking; fusion will use SAR where available.")
    vegetation = np.zeros(valid.shape, dtype=bool)
    indices = {"ndwi": ndwi, "ndbi": ndbi}
    if "red" in bands:
        ndvi = normalized_difference(bands["nir"], bands["red"])
        indices["ndvi"] = ndvi
        vegetation = ndvi > config.vegetation_threshold
        if np.any(valid & ~np.isfinite(ndvi)):
            warnings.append("Some red-band pixels are invalid; vegetation suppression is unavailable there.")
    else:
        warnings.append("Red band absent; optical built-up candidates do not use NDVI vegetation suppression.")
    water = clean_mask(ndwi > config.ndwi_threshold, valid, config.morphology_size, minimum)
    built = clean_mask((ndbi > config.ndbi_threshold) & ~vegetation, valid & ~water,
                       config.morphology_size, minimum)
    for index in indices.values():
        index[~valid] = np.nan
    return water, built, valid, raw_valid, quality_excluded, indices


def classes(water, built, valid):
    result = np.full(valid.shape, 255, dtype=np.uint8)
    result[valid] = 0
    result[built & valid] = 2
    result[water & valid] = 1
    return result


def validate_dates(metadata, config, warnings):
    result = {}
    for group, roles in (("optical", {"green", "nir", "swir", "red", "blue", "scl", "valid_mask"}),
                         ("sar", {"vv", "vh"})):
        selected = [m for role, m in metadata.items() if role in roles]
        dates = sorted({m["date"] for m in selected if m["date"]})
        if len(dates) > 1:
            raise DatasetError(f"The selected {group} bands have different acquisition dates: {dates}. Select one scene.")
        result[group] = dates[0] if dates else None
        if any(m["date"] is None for m in selected):
            warnings.append(f"Some {group} acquisition dates are unavailable; confirm the selected bands belong to one scene.")
    gap = None
    if all(result.values()):
        gap = abs((date.fromisoformat(result["optical"]) - date.fromisoformat(result["sar"])).days)
        if gap > config.max_date_gap_days:
            raise DatasetError(f"Acquisitions are {gap} days apart, exceeding max_date_gap_days={config.max_date_gap_days}.")
        if gap:
            warnings.append(f"Optical and SAR acquisitions are {gap} days apart; some differences may be temporal.")
    result["gap_days"] = gap
    return result


def grid_area(grid, warnings):
    if grid["crs"].is_projected:
        try:
            _, factor = grid["crs"].linear_units_factor
            return abs(grid["transform"].determinant) * factor ** 2
        except (ValueError, rasterio.errors.CRSError):
            pass
    warnings.append("Hectares are unavailable for this CRS; counts are reported in pixels. Reproject to a suitable local projected CRS for area estimates.")
    return None


def layer_stats(image, pixel_area):
    valid = image != 255
    count = int(valid.sum())
    result = {"valid_pixels": count}
    for label, value in (("water", 1), ("builtup", 2), ("other", 0)):
        n = int((image == value).sum())
        result[label] = {"pixels": n, "percent_of_valid": round(100 * n / count, 4) if count else None,
                         "area_ha": round(n * pixel_area / 10000, 6) if pixel_area is not None else None}
    return result


def prepare_dataset(sources, config):
    """Complete metadata checks before allocating raster arrays or writing output."""
    if not isinstance(config, Config):
        raise DatasetError("config must be a Config object.")
    validate_mapping(sources)
    warnings = ["Threshold baseline: candidate regions only. Bare soil, rough water, vegetation, radar shadow, and terrain can be confused with target classes. Accuracy has not been measured against ground truth."]
    metadata = {role: inspect_source(spec, config.max_pixels) for role, spec in sources.items()}
    if any(metadata[role]["dtype"].startswith(("uint", "int")) and metadata[role]["scale"] == 1
           and metadata[role]["offset"] == 0 for role in ("green", "nir", "swir")):
        warnings.append("Unscaled integer optical bands detected. Indices require compatible reflectance or a common zero-offset scale. Raw product-specific DN offsets are not inferred; supply scale/offset in the manifest when needed.")
    dates = validate_dates(metadata, config, warnings)
    with rasterio.open(sources["green"].path) as reference:
        grid = dict(crs=reference.crs, transform=reference.transform, width=reference.width,
                    height=reference.height, bounds=list(reference.bounds))
    pixel_area = grid_area(grid, warnings)
    minimum = config.min_component_pixels
    if config.min_component_m2 is not None:
        if pixel_area is None:
            raise DatasetError("min_component_m2 requires a projected grid with known linear units.")
        scene_pixels = grid["width"] * grid["height"]
        required_pixels = (scene_pixels + 1 if config.min_component_m2 > pixel_area * scene_pixels
                           else int(np.ceil(config.min_component_m2 / pixel_area)))
        minimum = max(minimum, required_pixels)
    for role, spec in sources.items():
        if role in {"vv", "vh"}:
            unit, origin = resolve_sar_units(spec, metadata[role], config.sar_units)
            metadata[role]["resolved_units"] = unit
            metadata[role]["units_source"] = origin
            if "convention" in origin or "filename" in origin:
                warnings.append(f"{role.upper()} units inferred from {origin}: {unit}. Override sar_units if exported differently.")
        bounds = transform_bounds(metadata[role]["crs"], grid["crs"], *metadata[role]["bounds"], densify_pts=21)
        target = grid["bounds"]
        if not all(np.isfinite(bounds)):
            raise DatasetError(f"{role} cannot be transformed to the optical grid; check CRS and bounds.")
        if min(bounds[2], target[2]) <= max(bounds[0], target[0]) or min(bounds[3], target[3]) <= max(bounds[1], target[1]):
            raise DatasetError(f"{role} does not overlap the optical reference geographically.")
    return metadata, grid, dates, warnings, pixel_area, minimum


def check_dataset(sources, config=None):
    """Read headers only. This cannot certify pixel validity or classification quality."""
    config = Config() if config is None else config
    metadata, grid, dates, warnings, pixel_area, minimum = prepare_dataset(sources, config)
    return {"status": "metadata_valid", "check_only": True, "parameters": asdict(config),
            "inputs": metadata, "dates": dates, "warnings": warnings,
            "reference_grid": {"crs": grid["crs"].to_string(), "transform": list(grid["transform"])[:6],
                               "width": grid["width"], "height": grid["height"], "bounds": grid["bounds"]},
            "pixel_area_m2": pixel_area, "resolved_min_component_pixels": minimum,
            "not_checked": ["pixel values and nodata coverage", "cloud-mask codes", "valid-data overlap fraction", "classification accuracy"],
            "next_step": "Run without --check-only to inspect pixels and generate maps."}


def run_pipeline(sources, output_dir, config=None):
    """Run a single pair. Publish complete runs without overwriting previous results."""
    from .reporting import write_outputs

    config = Config() if config is None else config
    metadata, grid, dates, warnings, pixel_area, minimum = prepare_dataset(sources, config)
    bands = {role: read_aligned(spec, metadata[role], grid, role, metadata[role].get("resolved_units"))
             for role, spec in sources.items()}
    raw_valid = None
    quality_sources = {role: (sources[role], metadata[role]) for role in ("scl", "valid_mask") if role in sources}
    if quality_sources:
        raw_valid = np.isfinite(normalized_difference(bands["green"], bands["nir"])) & np.isfinite(normalized_difference(bands["swir"], bands["nir"]))
        for role in quality_sources:
            quality_valid(bands[role], role)  # Validate categorical codes before any masked reread.
        for role in ("green", "nir", "swir", "red", "blue"):
            if role in sources:
                bands[role] = read_aligned(sources[role], metadata[role], grid, role, quality_sources=quality_sources)
    ow, ob, ov, raw_valid, quality_excluded, indices = classify_optical(bands, config, minimum, warnings, raw_valid)
    sw, sb, sv, sar_db, thresholds = classify_sar(bands, config, minimum, warnings)
    paired = raw_valid & sv
    overlap = float(paired.sum() / raw_valid.sum())
    if overlap < config.min_overlap:
        raise DatasetError(f"SAR overlaps only {overlap:.1%} of valid optical pixels; minimum is {config.min_overlap:.1%}. "
                           "Select matching scenes, crop to their common area, or explicitly lower min_overlap.")
    union_valid = ov | sv
    fw = ow | sw
    fb = (ob | sb) & ~fw
    maps = {"optical_only": classes(ow, ob, ov), "sar_only": classes(sw, sb, sv),
            "fused": classes(fw, fb, union_valid)}
    water_added = fw & ~ow
    built_added = fb & ~ob
    removed_built = ob & fw
    filled = sv & ~ov
    changed = maps["fused"] != maps["optical_only"]
    nwater, nbuilt = int(water_added.sum()), int(built_added.sum())
    nfilled, nchanged = int(filled.sum()), int(changed.sum())
    sar_contribution = f"SAR added {nwater:,} water-candidate pixels and {nbuilt:,} built-up-candidate pixels to the optical detections"
    if nfilled:
        sar_contribution += f", and supplied coverage for {nfilled:,} pixels with no valid optical classification"
    sar_contribution += "."
    if removed_built.any():
        sar_contribution += f" Water priority replaced {int(removed_built.sum()):,} optical built-up pixels."
    if not nchanged:
        warnings.append("Fused and optical-only maps are identical for this pair/settings. No artificial differences were introduced.")
        sar_contribution = "SAR produced no additional detections or coverage changes for this pair and these settings."
    if overlap < 0.99:
        warnings.append(f"SAR covers {overlap:.1%} of valid optical index pixels; remaining optical coverage uses optical evidence alone.")
    common = ov & sv
    stats = {key: layer_stats(value, pixel_area) for key, value in maps.items()}
    if pixel_area is not None:
        warnings.append("Area values are projected grid estimates; projection distortion and classification error are not corrected.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    output_dir = Path(output_dir).expanduser().resolve()
    final_dir = output_dir / run_id
    result = {
        "task": "optical_sar", "tools": ["checker_v1", "optical_sar_v1"],
        "parameters": {**asdict(config), "resolved_sar_thresholds": thresholds, "resolved_min_component_pixels": minimum},
        "facts": {
            "method": "optical indices + calibrated SAR power thresholds + class union with water priority",
            "sar_contribution": sar_contribution, "layers": stats,
            "sar_added_water_pixels": nwater, "sar_added_builtup_pixels": nbuilt,
            "optical_builtup_replaced_by_water_pixels": int(removed_built.sum()),
            "sar_filled_optical_invalid_pixels": nfilled,
            "sar_filled_quality_masked_pixels": int((sv & quality_excluded).sum()),
            "changed_from_optical_pixels": nchanged, "fused_differs_from_optical": bool(nchanged),
            "overlap_fraction_of_optical": round(overlap, 6), "common_valid_pixels": int(common.sum()),
            "sensor_agreement_fraction": round(float((maps["optical_only"][common] == maps["sar_only"][common]).mean()), 6) if common.any() else None,
            "confidence_status": "not calibrated; confidence=0.0 is the numeric contract placeholder, not measured accuracy",
            "dates": dates, "pixel_area_m2": pixel_area,
            "area_method": "projected grid estimate" if pixel_area is not None else "unavailable",
            "class_legend": {"0": "other/unclassified", "1": "water candidate", "2": "built-up candidate", "255": "nodata"},
        },
        "answer_text": "Built-up and water candidates from optical + SAR. " + sar_contribution,
        "confidence": 0.0, "warnings": warnings,
        "overlay": {"type": "landcover_mask", "file": str(final_dir / "fused.tif")},
        "layers": {key: str(final_dir / f"{key}.png") for key in maps},
        "receipt": {
            "software": {"tool3": __version__, "python": platform.python_version(), "numpy": np.__version__,
                         "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__, "opencv": cv.__version__},
            "why_this_tool": "Optical reflectance and calibrated SAR cover the same area; both contribute to candidate maps.",
            "rejected": False, "reason": None, "run_id": run_id, "output_dir": str(final_dir),
            "fusion_rule": "Use either valid sensor; union water first, then union built-up excluding water; no valid sensor = nodata.",
            "reference_grid": {"band": "green", "crs": grid["crs"].to_string(), "transform": list(grid["transform"])[:6],
                               "width": grid["width"], "height": grid["height"], "bounds": grid["bounds"]},
            "inputs": metadata,
            "preprocessing": "Per-band masks/nodata and scale/offset; supplied optical quality masks applied on native band grids before bilinear resampling and on the final grid. SAR converted to linear power before area averaging, then masked box mean and dB. Quality masks nearest. Affine georeferencing is trusted; no feature-based registration or raw SAR calibration is performed.",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    # Temp directory is owned by this invocation; its lifecycle is bounded to this run.
    with tempfile.TemporaryDirectory(prefix=".pending_", dir=output_dir) as temporary:
        stage = Path(temporary)
        masks = {"optical_water_mask": (ow, ov), "optical_builtup_mask": (ob, ov),
                 "sar_water_mask": (sw, sv), "sar_builtup_mask": (sb, sv),
                 "fused_water_mask": (fw, union_valid), "fused_builtup_mask": (fb, union_valid)}
        write_outputs(stage, result, maps, masks, grid, indices, bands, sar_db)
        publish_run(stage, final_dir)
    latest_temp = output_dir / f".latest_{run_id}.json"
    latest_temp.write_text(json.dumps({"run_id": run_id, "result": str(final_dir / "result.json"),
                                       "report": str(final_dir / "report.html")}, indent=2), encoding="utf-8")
    publish_latest(latest_temp, output_dir / "latest.json")
    return result
