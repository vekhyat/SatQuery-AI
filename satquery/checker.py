from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import rasterio
from affine import Affine
from rasterio.errors import RasterioIOError

from satquery.contracts import (
    AssetRecord,
    Bounds,
    MetadataProvenance,
    Modality,
    ModalityHint,
    RasterMetadata,
    TraceStep,
    ValueProvenance,
)
from satquery.errors import SatQueryError

CHECKER_VERSION = "checker_v1"
GRID_TOLERANCE = 1e-9

SAFE_TAG_KEYS = {
    "ACQUISITION_DATE",
    "DATE_ACQUIRED",
    "DATETIME",
    "SENSING_TIME",
    "TIFFTAG_DATETIME",
    "MISSION",
    "MODALITY",
    "PLATFORM",
    "PRODUCT",
    "SATELLITE",
    "SENSOR",
    "SENSOR_TYPE",
}
SAR_MARKERS = ("sentinel-1", "synthetic aperture", " radar", "sar")
OPTICAL_MARKERS = ("sentinel-2", "optical", "multispectral", "true color", "rgb")


@dataclass(slots=True)
class PackCheck:
    ok: bool
    reason: str | None = None
    code: str | None = None
    warnings: list[str] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)


def _selected_tags(dataset: rasterio.DatasetReader) -> dict[str, str]:
    selected: dict[str, str] = {}
    for key, value in dataset.tags().items():
        normalized_key = key.upper()
        if normalized_key in SAFE_TAG_KEYS:
            selected[normalized_key] = str(value)[:256]
    return selected


def _detect_modality(
    tags: dict[str, str], descriptions: list[str | None], band_count: int
) -> tuple[Modality, str]:
    tag_text = " ".join([*tags.keys(), *tags.values()]).lower()
    description_text = " ".join(value or "" for value in descriptions).lower()
    combined = f" {tag_text} {description_text} "
    tokens = set(re.findall(r"[a-z0-9-]+", combined))

    if any(marker in combined for marker in SAR_MARKERS) or {"vv", "vh"} & tokens:
        source = "band_description" if description_text.strip() else "tag"
        return Modality.SAR, source
    if any(marker in combined for marker in OPTICAL_MARKERS):
        source = "band_description" if description_text.strip() else "tag"
        return Modality.OPTICAL, source
    if band_count >= 3:
        return Modality.OPTICAL, "band_count_heuristic"
    return Modality.UNKNOWN, "unknown"


def _parse_date_value(raw: str) -> date | None:
    candidate = raw.strip()
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y:%m:%d %H:%M:%S",
        "%Y%m%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(candidate[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    match = re.search(r"\b(\d{4})[-:]([01]\d)[-:]([0-3]\d)\b", candidate)
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    return None


def _detect_date(tags: dict[str, str]) -> tuple[date | None, str]:
    for key in (
        "ACQUISITION_DATE",
        "DATE_ACQUIRED",
        "SENSING_TIME",
        "DATETIME",
        "TIFFTAG_DATETIME",
    ):
        if key in tags:
            parsed = _parse_date_value(tags[key])
            if parsed is not None:
                return parsed, "tag"
    return None, "unknown"


def inspect_raster(
    path: Path,
    modality_hint: ModalityHint = ModalityHint.AUTO,
    acquisition_date_hint: date | None = None,
) -> tuple[RasterMetadata, list[str]]:
    warnings: list[str] = []
    try:
        with rasterio.open(path) as dataset:
            if dataset.driver != "GTiff":
                raise SatQueryError(
                    415,
                    "unsupported_media_type",
                    "The uploaded file is not an internal GeoTIFF dataset.",
                    {"driver": dataset.driver},
                )
            if dataset.width <= 0 or dataset.height <= 0 or dataset.count <= 0:
                raise SatQueryError(
                    422,
                    "invalid_raster_dimensions",
                    "The GeoTIFF must contain at least one non-empty raster band.",
                )
            if dataset.crs is None:
                raise SatQueryError(
                    422,
                    "missing_crs",
                    "The GeoTIFF does not declare a coordinate reference system.",
                )
            if dataset.transform == Affine.identity():
                raise SatQueryError(
                    422,
                    "invalid_transform",
                    "The GeoTIFF must declare a non-identity geospatial transform.",
                )

            bounds_values = tuple(dataset.bounds)
            if not all(math.isfinite(value) for value in bounds_values):
                raise SatQueryError(
                    422,
                    "invalid_bounds",
                    "The GeoTIFF contains non-finite geographic bounds.",
                )

            tags = _selected_tags(dataset)
            descriptions = [
                description[:256] if description is not None else None
                for description in dataset.descriptions
            ]
            detected_modality, detected_modality_source = _detect_modality(
                tags, descriptions, dataset.count
            )
            detected_date, detected_date_source = _detect_date(tags)

            if modality_hint is ModalityHint.AUTO:
                modality = detected_modality
                modality_source = detected_modality_source
            else:
                modality = Modality(modality_hint.value)
                modality_source = "user"
                if detected_modality not in (Modality.UNKNOWN, modality):
                    warnings.append(
                        "The supplied modality overrides conflicting modality metadata."
                    )

            if acquisition_date_hint is not None:
                acquisition_date = acquisition_date_hint
                acquisition_date_source = "user"
                if detected_date is not None and detected_date != acquisition_date_hint:
                    warnings.append(
                        "The supplied acquisition date overrides a conflicting embedded date."
                    )
            else:
                acquisition_date = detected_date
                acquisition_date_source = detected_date_source

            if modality is Modality.UNKNOWN:
                warnings.append(
                    "Modality could not be inferred; re-upload with optical or sar supplied."
                )
            if (
                modality_hint is ModalityHint.AUTO
                and detected_modality_source == "band_count_heuristic"
            ):
                warnings.append(
                    "Optical modality was inferred from band count; supply a hint to confirm it."
                )
            if acquisition_date is None:
                warnings.append(
                    "No acquisition date was found; temporal routing will require a supplied date."
                )

            nodata = dataset.nodata
            if nodata is not None and not math.isfinite(float(nodata)):
                nodata = None
                warnings.append("A non-finite no-data value was omitted from the response.")

            metadata = RasterMetadata(
                driver=dataset.driver,
                width=dataset.width,
                height=dataset.height,
                band_count=dataset.count,
                dtypes=list(dataset.dtypes),
                crs=dataset.crs.to_string(),
                bounds=Bounds(
                    left=dataset.bounds.left,
                    bottom=dataset.bounds.bottom,
                    right=dataset.bounds.right,
                    top=dataset.bounds.top,
                ),
                transform=list(dataset.transform)[:6],
                resolution=[abs(float(dataset.res[0])), abs(float(dataset.res[1]))],
                nodata=float(nodata) if nodata is not None else None,
                band_descriptions=descriptions,
                tags=tags,
                modality=modality,
                acquisition_date=acquisition_date,
                provenance=MetadataProvenance(
                    modality=ValueProvenance(
                        source=modality_source,
                        detected_value=(
                            None
                            if detected_modality is Modality.UNKNOWN
                            else detected_modality.value
                        ),
                        detected_source=detected_modality_source,
                    ),
                    acquisition_date=ValueProvenance(
                        source=acquisition_date_source,
                        detected_value=(
                            detected_date.isoformat() if detected_date is not None else None
                        ),
                        detected_source=detected_date_source,
                    ),
                ),
            )
            return metadata, warnings
    except SatQueryError:
        raise
    except RasterioIOError as exc:
        raise SatQueryError(
            422,
            "corrupt_geotiff",
            "Rasterio could not open the uploaded GeoTIFF.",
        ) from exc
    except (OSError, ValueError) as exc:
        raise SatQueryError(
            422,
            "invalid_geotiff",
            "The uploaded GeoTIFF contains invalid metadata.",
        ) from exc


def check_pack(assets: list[AssetRecord]) -> PackCheck:
    if len({asset.asset_id for asset in assets}) != len(assets):
        reason = "Each query asset ID must be unique."
        return PackCheck(
            ok=False,
            code="duplicate_asset",
            reason=reason,
            trace=[TraceStep(stage="checker", status="rejected", message=reason)],
        )

    if len(assets) == 1:
        message = "One individually valid GeoTIFF is available for routing."
        return PackCheck(
            ok=True,
            trace=[TraceStep(stage="checker", status="ok", message=message)],
        )

    first, second = assets
    first_meta = first.metadata
    second_meta = second.metadata
    mismatches: list[str] = []
    if first_meta.crs != second_meta.crs:
        mismatches.append("CRS")
    if (first_meta.width, first_meta.height) != (second_meta.width, second_meta.height):
        mismatches.append("dimensions")
    if any(
        not math.isclose(left, right, rel_tol=0.0, abs_tol=GRID_TOLERANCE)
        for left, right in zip(first_meta.transform, second_meta.transform, strict=True)
    ):
        mismatches.append("affine grid")

    if mismatches:
        reason = (
            "The GeoTIFF pair requires reprojection or resampling because these fields "
            f"do not match: {', '.join(mismatches)}."
        )
        return PackCheck(
            ok=False,
            code="incompatible_grid",
            reason=reason,
            trace=[
                TraceStep(
                    stage="checker",
                    status="rejected",
                    message=reason,
                    details={"mismatches": mismatches},
                )
            ],
        )

    message = "Both GeoTIFFs share the same CRS, dimensions, and affine grid."
    return PackCheck(
        ok=True,
        trace=[TraceStep(stage="checker", status="ok", message=message)],
    )
