"""Explicit band mapping, conservative discovery, and masked reprojection."""

from dataclasses import dataclass
from datetime import date
import json
import math
from pathlib import Path
import re

import numpy as np
import rasterio
from rasterio.enums import MaskFlags, Resampling
from rasterio.warp import reproject, transform_bounds


class DatasetError(ValueError):
    """An actionable problem with the supplied dataset or configuration."""


def local_path(value):
    """Normalize a configured path, reporting malformed paths as data errors."""
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\x00" in str(value):
        raise DatasetError("Expected a nonempty local path without NUL characters.")
    try:
        return Path(value).expanduser().resolve()
    except (ValueError, RuntimeError) as exc:
        raise DatasetError("Invalid local path.") from exc


def finite_number(value):
    """JSON booleans and oversized integers are not valid numeric configuration."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def read_json(path):
    """Reject duplicate JSON keys; silently replacing a band choice is unsafe."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DatasetError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    except (OSError, ValueError) as exc:
        raise DatasetError(f"Cannot read JSON {path}: {exc}") from exc


@dataclass(frozen=True)
class BandSource:
    path: Path
    band: int = 1
    scale: float | None = None
    offset: float | None = None
    nodata: float | None = None
    units: str | None = None

    def __post_init__(self):
        if not isinstance(self.path, (str, Path)) or not str(self.path).strip():
            raise DatasetError("Band path must be a nonempty local file path.")
        object.__setattr__(self, "path", local_path(self.path))
        if type(self.band) is not int or self.band < 1:
            raise DatasetError("Band indexes must be positive, one-based integers.")
        for name in ("scale", "offset", "nodata"):
            value = getattr(self, name)
            if value is not None and not finite_number(value):
                raise DatasetError(f"{name} must be a finite number when supplied.")
        if self.scale is not None and self.scale <= 0:
            raise DatasetError("Band scale must be greater than zero.")
        if self.units not in (None, "linear", "db"):
            raise DatasetError("Band units must be 'linear' or 'db'.")


ALIASES = {
    "B02": "blue", "B2": "blue", "BLUE": "blue",
    "B03": "green", "B3": "green", "GREEN": "green",
    "B04": "red", "B4": "red", "RED": "red",
    "B08": "nir", "B8": "nir", "NIR": "nir",
    "B11": "swir", "SWIR": "swir", "SWIR1": "swir",
    "VV": "vv", "VH": "vh", "SCL": "scl", "VALID_MASK": "valid_mask",
}
REQUIRED = {"green", "nir", "swir", "vv"}


def identify(text):
    tokens = re.findall(r"(?<![A-Z0-9])(B0?[2348]|B11|BLUE|GREEN|RED|NIR|SWIR1?|VV|VH|SCL|VALID_MASK)(?![A-Z0-9])", text.upper())
    # Browser names contain the acquisition mode VV_VH, followed by the actual band.
    browser_band = re.search(r"_(VV|VH)_\(RAW\)$", text.upper())
    if browser_band:
        return ALIASES[browser_band.group(1)]
    roles = {ALIASES[token] for token in tokens}
    return roles.pop() if len(roles) == 1 else None


def validate_mapping(sources):
    if not isinstance(sources, dict) or not all(isinstance(key, str) for key in sources):
        raise DatasetError("Band mapping must be a dictionary of role names to BandSource objects.")
    missing = REQUIRED - sources.keys()
    if missing:
        raise DatasetError("Missing required bands: " + ", ".join(sorted(missing)) +
                           ". Supply green/NIR/SWIR reflectance and calibrated VV backscatter; "
                           "use --manifest for custom filenames or multiband rasters.")
    unknown = sources.keys() - set(ALIASES.values())
    if unknown:
        raise DatasetError("Unknown band roles: " + ", ".join(sorted(unknown)))
    seen = {}
    for role, spec in sources.items():
        if not isinstance(spec, BandSource):
            raise DatasetError(f"{role} must be a BandSource.")
        key = (spec.path, spec.band)
        if key in seen:
            raise DatasetError(f"{role} and {seen[key]} select the same file and band.")
        seen[key] = role


def discover(optical_dir, sar_dir):
    """Discover one scene only. Multiple candidate bands require explicit selection."""
    found = {}
    for folder, roles in ((optical_dir, {"blue", "green", "red", "nir", "swir", "scl", "valid_mask"}),
                          (sar_dir, {"vv", "vh"})):
        folder = Path(folder).expanduser().resolve()
        if not folder.is_dir():
            raise DatasetError(f"Input folder does not exist: {folder}")
        paths = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".tif", ".tiff", ".jp2"})
        if not paths:
            raise DatasetError(f"No TIFF/JP2 rasters found in {folder}. Extract archives first.")
        for path in paths:
            with rasterio.open(path) as src:
                for index in src.indexes:
                    description = src.descriptions[index - 1]
                    role = identify(description) if description else None
                    if role is None and src.count == 1:
                        role = identify(path.stem)
                    if role in roles:
                        if role in found:
                            raise DatasetError(f"Multiple candidates for {role}: {found[role].path.name}, "
                                               f"{path.name}. Use one scene per folder or --manifest.")
                        found[role] = BandSource(path, index)
    validate_mapping(found)
    return found


def load_manifest(path):
    """Read paths relative to the manifest, not the shell's working directory."""
    path = Path(path).expanduser().resolve()
    return parse_manifest(read_json(path), path.parent)


def parse_manifest(raw, base_dir):
    """Validate an in-memory manifest; paths are resolved against an explicit base."""
    if not isinstance(base_dir, (str, Path)) or not str(base_dir).strip():
        raise DatasetError("base_dir must be a nonempty local directory path.")
    base_dir = local_path(base_dir)
    if not isinstance(raw, dict) or set(raw) - {"bands", "parameters"}:
        raise DatasetError("Manifest must contain 'bands' and optional 'parameters' only.")
    if not isinstance(raw.get("bands"), dict) or not isinstance(raw.get("parameters", {}), dict):
        raise DatasetError("Manifest bands and parameters must be JSON objects.")
    result = {}
    for role, value in raw["bands"].items():
        if isinstance(value, str):
            value = {"path": value}
        if not isinstance(value, dict) or "path" not in value or not isinstance(value["path"], str) or not value["path"].strip():
            raise DatasetError(f"Band {role} needs a path string or an object with a path.")
        extra = set(value) - {"path", "band", "scale", "offset", "nodata", "units"}
        if extra:
            raise DatasetError(f"Unknown fields for {role}: {sorted(extra)}")
        args = dict(value)
        args["path"] = base_dir / value["path"]
        result[role] = BandSource(**args)
    validate_mapping(result)
    return result, raw.get("parameters", {})


def acquisition_date(path, tags):
    for key in ("ACQUISITION_DATE", "SENSING_TIME", "DATE_ACQUIRED", "datetime", "start_datetime"):
        if key in tags:
            match = re.search(r"(\d{4})[-:]?(\d{2})[-:]?(\d{2})", tags[key])
            if match:
                try:
                    return date(*map(int, match.groups())).isoformat()
                except ValueError:
                    pass
    match = re.search(r"(?<!\d)(20\d{2})-?(\d{2})-?(\d{2})(?!\d)", path.name)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return None


def inspect_source(spec, max_pixels):
    if not spec.path.is_file():
        raise DatasetError(f"Input file does not exist: {spec.path}")
    with rasterio.open(spec.path) as src:
        if spec.band > src.count:
            raise DatasetError(f"{spec.path.name} has {src.count} bands, not {spec.band}.")
        if src.crs is None:
            raise DatasetError(f"{spec.path.name} has no CRS. Supply an orthorectified, georeferenced raster.")
        transform = src.transform
        if not all(np.isfinite(tuple(transform))) or abs(transform.determinant) < 1e-15:
            raise DatasetError(f"{spec.path.name} has an invalid pixel transform.")
        if transform.is_identity:
            raise DatasetError(f"{spec.path.name} has an identity transform; georeference it before fusion.")
        if src.width * src.height > max_pixels:
            raise DatasetError(f"{spec.path.name} exceeds max_pixels={max_pixels:,}. Crop to your area of interest "
                               "or raise --max-pixels only if sufficient RAM is available.")
        if np.dtype(src.dtypes[spec.band - 1]).kind not in "uif":
            raise DatasetError(f"{spec.path.name}: only real-valued rasters are supported, not complex SAR/SLC.")
        scale = spec.scale if spec.scale is not None else src.scales[spec.band - 1]
        offset = spec.offset if spec.offset is not None else src.offsets[spec.band - 1]
        if not np.isfinite(scale) or scale <= 0 or not np.isfinite(offset):
            raise DatasetError(f"Invalid calibration scale/offset in {spec.path.name}.")
        return {
            "path": str(spec.path), "band": spec.band, "width": src.width, "height": src.height,
            "crs": src.crs.to_string(), "transform": list(transform)[:6], "bounds": list(src.bounds),
            "dtype": src.dtypes[spec.band - 1], "scale": scale, "offset": offset,
            "file_size_bytes": spec.path.stat().st_size, "file_mtime_ns": spec.path.stat().st_mtime_ns,
            "nodata": spec.nodata if spec.nodata is not None else (src.nodata if src.nodata is None or np.isfinite(src.nodata) else str(src.nodata)),
            "date": acquisition_date(spec.path, src.tags()),
            "description": src.descriptions[spec.band - 1],
            "unit_metadata": " ".join(filter(None, [src.units[spec.band - 1]] +
                [value for tags in (src.tags(), src.tags(spec.band)) for key, value in tags.items()
                 if key.lower() in {"units", "unittype"}])),
        }


def resolve_sar_units(spec, metadata, requested):
    if spec.units:
        return spec.units, "manifest band units"
    if requested != "auto":
        return requested, "configured sar_units"
    text = metadata["unit_metadata"].upper()
    db = bool(re.search(r"\bDB\b|DECIBEL", text))
    linear = bool(re.search(r"\bLINEAR(?:_POWER)?\b|\bPOWER\b", text))
    if db and linear:
        raise DatasetError(f"Conflicting SAR unit metadata in {spec.path.name}; set explicit band units or sar_units.")
    if db:
        return "db", "raster unit metadata"
    if linear:
        return "linear", "raster unit metadata"
    if re.search(r"(?<![A-Z0-9])DB(?![A-Z0-9])", spec.path.stem.upper()):
        return "db", "filename DB token"
    if "SENTINEL-1" in spec.path.name.upper() and "(RAW)" in spec.path.name.upper() and metadata["dtype"].startswith("float"):
        return "linear", "Copernicus Browser Sentinel-1 Raw export naming convention"
    raise DatasetError(f"SAR units are unknown for {spec.path.name}. Set --sar-units linear for calibrated "
                       "linear power, or --sar-units db for calibrated decibels. Raw amplitude/DN needs calibration first.")


def read_aligned(spec, meta, grid, role, units=None, quality_sources=None):
    """Mask first, calibrate, then warp values and coverage separately."""
    bounds = transform_bounds(meta["crs"], grid["crs"], *meta["bounds"], densify_pts=21)
    target = grid["bounds"]
    if min(bounds[2], target[2]) <= max(bounds[0], target[0]) or min(bounds[3], target[3]) <= max(bounds[1], target[1]):
        raise DatasetError(f"{role} does not overlap the optical reference geographically.")
    with rasterio.open(spec.path) as src:
        raw = src.read(spec.band, out_dtype="float32")
        valid = np.isfinite(raw)
        # An explicit nodata value replaces the header sentinel, while actual
        # dataset/alpha masks remain authoritative. A nodata-derived mask must not
        # erase valid zero-dB pixels when the caller corrects a bad nodata header.
        flags = src.mask_flag_enums[spec.band - 1]
        if spec.nodata is None or MaskFlags.per_dataset in flags or MaskFlags.alpha in flags:
            valid &= src.read_masks(spec.band) > 0
        if spec.nodata is not None:
            valid &= raw != spec.nodata
        with np.errstate(over="ignore", invalid="ignore"):
            data = raw * np.float32(meta["scale"]) + np.float32(meta["offset"])
        valid &= np.isfinite(data)
        if quality_sources:
            native_grid = dict(crs=src.crs, transform=src.transform, width=src.width,
                               height=src.height, bounds=list(src.bounds))
            for quality_role, (quality_spec, quality_meta) in quality_sources.items():
                # Read quality on this band's native grid so cloudy source pixels
                # cannot participate in bilinear interpolation into a clear output.
                quality = read_aligned(quality_spec, dict(quality_meta), native_grid, quality_role)
                valid &= quality_valid(quality, quality_role)
            meta["quality_masked_before_resampling"] = True
        if units == "linear":
            valid &= data > 0
        elif units == "db":
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                data = np.power(np.float32(10), data / np.float32(10))
            valid &= np.isfinite(data) & (data > 0)
        data[~valid] = np.nan
        aligned = np.full((grid["height"], grid["width"]), np.nan, dtype=np.float32)
        coverage = np.zeros(aligned.shape, dtype=np.uint8)
        same = src.crs == grid["crs"] and src.transform == grid["transform"] and src.shape == aligned.shape
        method = Resampling.nearest if role in {"scl", "valid_mask"} else (Resampling.average if units else Resampling.bilinear)
        if same:
            aligned[:] = data
            coverage[:] = valid
        else:
            kwargs = dict(src_transform=src.transform, src_crs=src.crs,
                          dst_transform=grid["transform"], dst_crs=grid["crs"])
            reproject(data, aligned, src_nodata=np.nan, dst_nodata=np.nan, resampling=method, **kwargs)
            reproject(valid.astype(np.uint8), coverage, src_nodata=0, dst_nodata=0,
                      resampling=Resampling.nearest, **kwargs)
        # Resampling must never turn a no-data hole into observed evidence.
        aligned[coverage == 0] = np.nan
        meta["alignment"] = "already aligned" if same else f"reprojected: {method.name}; validity: nearest"
        meta["aligned_valid_pixels"] = int(np.isfinite(aligned).sum())
        return aligned


def quality_valid(data, role):
    if role == "scl":
        observed = data[np.isfinite(data)]
        if observed.size and not np.isin(observed, np.arange(12)).all():
            raise DatasetError("SCL must contain Sentinel-2 integer scene classes 0 through 11.")
        return np.isin(data, [2, 4, 5, 6])
    return np.isfinite(data) & (data > 0)
