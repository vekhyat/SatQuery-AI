"""M6 adapter for the team's AssetRecord + RoutePlan -> ToolResult contract."""
from copy import deepcopy
import json
import logging
from uuid import UUID

import rasterio

from satquery.contracts import AssetRecord, Modality, Overlay, OverlayType, RoutePlan, ToolResult
from satquery.errors import SatQueryError
from .context import ToolContext
from .tool3 import BandSource, Config, DatasetError, run_pipeline
from .tool3.artifacts import resolve_artifact, to_web_result
from .tool3.inputs import identify, read_json, validate_mapping

logger = logging.getLogger(__name__)


class ToolInputError(SatQueryError):
    """A supported route whose raster bands/values cannot be processed."""
    def __init__(self, message: str):
        super().__init__(422, "tool3_invalid_dataset", message)


def _sources(assets: list[AssetRecord], context: ToolContext):
    if len(assets) != 2 or {item.metadata.modality for item in assets} != {Modality.OPTICAL, Modality.SAR}:
        raise DatasetError("Tool 3 needs one optical and one SAR asset.")
    selected = {}
    for asset in assets:
        path = context.store.source_path(asset)
        allowed = ({"green", "nir", "swir", "red", "blue", "scl", "valid_mask"}
                   if asset.metadata.modality is Modality.OPTICAL else {"vv", "vh"})
        with rasterio.open(path) as src:
            for index, description in enumerate(src.descriptions, start=1):
                role = identify(description) if description else None
                if role is None and src.count == 1:
                    role = identify(asset.original_name.rsplit('.', 1)[0])
                if role in allowed:
                    if role in selected:
                        raise DatasetError(f"Duplicate {role} band descriptions; select one band per role.")
                    selected[role] = BandSource(path, band=index)
    validate_mapping(selected)
    dates = [asset.metadata.acquisition_date for asset in assets]
    if all(dates) and abs((dates[0] - dates[1]).days) > Config().max_date_gap_days:
        raise DatasetError("Uploaded optical/SAR acquisition dates are more than 30 days apart.")
    return selected


def optical_sar_v1(assets: list[AssetRecord], plan: RoutePlan, context: ToolContext | None = None) -> ToolResult:
    """Return only tool-owned fields; the service composes the answer and receipt.

The existing upload API accepts two stacks. Bands must have role descriptions
(green/NIR/SWIR and VV; optional red/blue/VH/quality). SAR units and calibration
come from GeoTIFF metadata. No positional band order or physical units are guessed.
"""
    if context is None:
        raise SatQueryError(500, "missing_tool_context", "Tool 3 requires a server execution context.")
    if not context.slots.acquire(blocking=False):
        raise SatQueryError(429, "tool3_busy", "Tool 3 is processing another scene; retry shortly.")
    try:
        sources = _sources(assets, context)
        result = run_pipeline(sources, context.output_dir, Config())
        run_id = result["receipt"]["run_id"]
        # Publish access metadata before returning any links. These IDs tie maps
        # to the same asset lifetime as the rest of the local API.
        access = context.output_dir / run_id / "access.json"
        access.write_text(json.dumps({"asset_ids": [str(item.asset_id) for item in assets]}), encoding="utf-8")
        public = to_web_result(result, output_dir=context.output_dir, artifact_base_url=context.artifact_base_url)
        facts = deepcopy(public["facts"])
        facts["layer_urls"] = public["layers"]
        facts["artifacts"] = public["receipt"]["artifacts"]
        facts["fusion_rule"] = public["receipt"]["fusion_rule"]
        facts["reference_grid"] = public["receipt"]["reference_grid"]
        facts["processing_parameters"] = public["parameters"]
        facts["software"] = public["receipt"]["software"]
        facts["uploaded_dates"] = {item.metadata.modality.value: str(item.metadata.acquisition_date) if item.metadata.acquisition_date else None for item in assets}
        return ToolResult(facts=facts, confidence=0.0, warnings=public["warnings"],
                          overlay=Overlay(type=OverlayType.HEATMAP, file=public["layers"]["fused"]))
    except DatasetError as exc:
        # Dataset errors are useful to the uploader, but local paths are private.
        reason = str(exc).replace(str(context.store.root), "[upload storage]")
        raise ToolInputError(reason) from exc
    except MemoryError as exc:
        raise ToolInputError("Scene exceeds available memory; crop it before uploading.") from exc
    except (OSError, rasterio.errors.RasterioError) as exc:
        logger.exception("Tool 3 raster/output I/O failed")
        raise SatQueryError(500, "tool3_io_error", "Tool 3 could not read the scene or save its maps. Check server logs.") from exc
    finally:
        context.slots.release()


def artifact_path(context: ToolContext, run_id: str, filename: str):
    try:
        path = resolve_artifact(context.output_dir, run_id, filename)
        access = path.parent / "access.json"
        if access.resolve().parent != path.parent:
            raise DatasetError("Invalid access record.")
        asset_ids = read_json(access).get("asset_ids")
        if not isinstance(asset_ids, list) or len(asset_ids) != 2:
            raise DatasetError("Invalid access record.")
        for asset_id in asset_ids:
            context.store.load(UUID(asset_id))
        return path
    except (DatasetError, OSError, ValueError, TypeError) as exc:
        raise SatQueryError(404, "tool3_artifact_not_found", "The map is unavailable or its source assets have expired.") from exc
