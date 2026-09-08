"""Inactive main-side adapter for the isolated MCI change worker."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from rasterio.crs import CRS

from satquery.contracts import AssetRecord, Modality, Overlay, OverlayType, RoutePlan, Task, ToolResult
from satquery.errors import SatQueryError
from satquery.tools.change_mci_protocol import (
    CONTRACT_VERSION,
    ChangeAnalysisRequest,
    ChangeAnalysisSuccessResponse,
)
from satquery.tools.context import ToolContext
from satquery.tools.mci_worker_client import MCIWorkerClient, MCIWorkerClientError


REQUIRED_ARTIFACTS = {
    "semantic_mask": "semantic_mask_raw.png",
    "semantic_mask_rgb": "semantic_mask_rgb.png",
    "binary_mask": "change_binary_mask.png",
    "overlay": "overlay.png",
    "components": "components.json",
}


class ChangeMCIAdapterError(SatQueryError):
    """Local adapter error until generic specialist errors are introduced later."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(status_code, code, message)


def build_change_mci_v1(
    client_factory: Callable[[], MCIWorkerClient],
) -> Callable[[list[AssetRecord], RoutePlan, ToolContext | None], ToolResult]:
    """Return the standard handler shape with a narrow, testable client seam."""

    def handler(
        assets: list[AssetRecord], plan: RoutePlan, context: ToolContext | None = None
    ) -> ToolResult:
        return _run_change_mci_v1(assets, plan, context, client_factory)

    return handler


def change_mci_v1(
    assets: list[AssetRecord], plan: RoutePlan, context: ToolContext | None = None
) -> ToolResult:
    """Map a validated temporal optical pair to the local MCI worker contract."""
    return _run_change_mci_v1(assets, plan, context, MCIWorkerClient)


def _run_change_mci_v1(
    assets: list[AssetRecord],
    plan: RoutePlan,
    context: ToolContext | None,
    client_factory: Callable[[], MCIWorkerClient],
) -> ToolResult:
    if context is None:
        raise ChangeMCIAdapterError("tool2_missing_context", "Tool 2 requires a server execution context.", 500)
    if plan.task is not Task.CHANGE:
        raise ChangeMCIAdapterError("tool2_invalid_plan", "Tool 2 requires a temporal-change plan.")
    if len(assets) != 2 or len(plan.ordered_asset_ids) != 2:
        raise ChangeMCIAdapterError("tool2_invalid_assets", "Tool 2 requires exactly two ordered optical assets.")
    if len(set(plan.ordered_asset_ids)) != 2:
        raise ChangeMCIAdapterError("tool2_invalid_plan", "Tool 2 requires two distinct ordered asset IDs.")
    asset_by_id = {asset.asset_id: asset for asset in assets}
    if len(asset_by_id) != 2 or any(asset_id not in asset_by_id for asset_id in plan.ordered_asset_ids):
        raise ChangeMCIAdapterError("tool2_invalid_plan", "The plan references assets that are unavailable.")
    before_id, after_id = plan.ordered_asset_ids
    _check_parameter_order(plan, before_id, after_id)
    before, after = asset_by_id[before_id], asset_by_id[after_id]
    _preflight_pair(before, after)

    before_path = context.store.source_path(before)
    after_path = context.store.source_path(after)
    request = ChangeAnalysisRequest(
        contract_version=CONTRACT_VERSION,
        request_id=uuid4(),
        before_path=str(before_path),
        after_path=str(after_path),
        geo_metadata=_geo_metadata(before),
    )
    try:
        response = client_factory().analyze(request)
    except MCIWorkerClientError as error:
        raise ChangeMCIAdapterError(
            "tool2_worker_" + error.code.lower(),
            "Tool 2 worker analysis is unavailable.",
            error.http_status or 502,
        ) from error
    if response.request_id != request.request_id:
        raise ChangeMCIAdapterError("tool2_invalid_worker_response", "Tool 2 worker response did not match the request.", 502)
    artifact_paths = _verify_artifacts(response, context.output_dir)
    _write_access_manifest(artifact_paths["overlay"].parent, before_id, after_id, response.run_id)
    return _to_tool_result(response, context.artifact_base_url)


def _check_parameter_order(plan: RoutePlan, before_id: UUID, after_id: UUID) -> None:
    for parameter, expected in (("before_asset_id", before_id), ("after_asset_id", after_id)):
        actual = plan.parameters.get(parameter)
        if actual is not None and str(actual) != str(expected):
            raise ChangeMCIAdapterError("tool2_invalid_plan", "The plan temporal ordering is inconsistent.")


def _preflight_pair(before: AssetRecord, after: AssetRecord) -> None:
    for asset in (before, after):
        metadata = asset.metadata
        if metadata.modality is not Modality.OPTICAL:
            raise ChangeMCIAdapterError("tool2_invalid_input", "Tool 2 requires optical GeoTIFF assets.")
        if (metadata.width, metadata.height) != (256, 256):
            raise ChangeMCIAdapterError("tool2_invalid_input", "Tool 2 requires 256x256 input images.")
        if metadata.band_count != 3 or len(metadata.dtypes) != 3:
            raise ChangeMCIAdapterError("tool2_invalid_input", "Tool 2 requires exactly three image bands.")
        if any(dtype.lower() != "uint8" for dtype in metadata.dtypes):
            raise ChangeMCIAdapterError("tool2_invalid_input", "Tool 2 requires uint8 image bands.")
    if (
        before.metadata.crs != after.metadata.crs
        or before.metadata.transform != after.metadata.transform
        or before.metadata.resolution != after.metadata.resolution
    ):
        raise ChangeMCIAdapterError("tool2_invalid_input", "Tool 2 requires an exact compatible input grid.")


def _geo_metadata(asset: AssetRecord) -> dict[str, object]:
    metadata = asset.metadata
    unavailable: dict[str, object] = {"validated": False}
    try:
        crs = CRS.from_user_input(metadata.crs)
        units = str(crs.linear_units or "").lower()
        pixel_width, pixel_height = metadata.resolution
        if (
            crs.is_projected
            and units in {"m", "meter", "meters", "metre", "metres"}
            and math.isfinite(pixel_width)
            and math.isfinite(pixel_height)
            and pixel_width > 0
            and pixel_height > 0
        ):
            return {
                "validated": True,
                "crs": crs.to_string(),
                "is_projected": True,
                "linear_units": units,
                "pixel_width": pixel_width,
                "pixel_height": pixel_height,
            }
    except (ValueError, TypeError):
        pass
    return unavailable


def _verify_artifacts(
    response: ChangeAnalysisSuccessResponse, output_root: Path
) -> dict[str, Path]:
    if response.run_id != response.run_id.lower() or not response.run_id.isalnum():
        raise ChangeMCIAdapterError("tool2_invalid_worker_response", "Tool 2 worker returned an unsafe run ID.", 502)
    advertised = response.artifacts.model_dump()
    if advertised != REQUIRED_ARTIFACTS:
        raise ChangeMCIAdapterError("tool2_invalid_worker_response", "Tool 2 worker returned an invalid artifact set.", 502)
    root = output_root.resolve()
    run_directory = (root / response.run_id).resolve()
    try:
        run_directory.relative_to(root)
    except ValueError as error:
        raise ChangeMCIAdapterError("tool2_invalid_worker_response", "Tool 2 worker artifact location is invalid.", 502) from error
    paths: dict[str, Path] = {}
    for name, filename in advertised.items():
        path = (run_directory / filename).resolve()
        if path.parent != run_directory or not path.is_file():
            raise ChangeMCIAdapterError("tool2_missing_artifact", "Tool 2 worker artifact is unavailable.", 502)
        paths[name] = path
    return paths


def _write_access_manifest(run_directory: Path, before_id: UUID, after_id: UUID, run_id: str) -> None:
    target = run_directory / "access.json"
    temporary = run_directory / "access.json.tmp"
    payload = {"asset_ids": [str(before_id), str(after_id)], "run_id": run_id, "tool": "change_mci_v1"}
    temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _to_tool_result(response: ChangeAnalysisSuccessResponse, artifact_base_url: str) -> ToolResult:
    base_url = artifact_base_url.rstrip("/")
    public_artifacts = {
        name: f"{base_url}/{response.run_id}/{filename}"
        for name, filename in response.artifacts.model_dump().items()
    }
    warnings = [warning for warning in response.warnings if not _looks_like_path(warning)]
    if not any("confidence" in warning.lower() for warning in warnings):
        warnings.append("Model confidence is not calibrated; confidence=0.0 is a compatibility sentinel.")
    facts = {
        "summary": response.caption.text,
        "caption": response.caption.model_dump(),
        **response.statistics.model_dump(),
        "classes": {
            name: class_statistics.model_dump()
            for name, class_statistics in response.statistics.per_class.items()
        },
        "components": response.components.model_dump(),
        **response.geospatial.model_dump(),
        "confidence_status": response.confidence.status,
        "confidence_provenance": response.confidence.model_dump(),
        "model": response.model.model_dump(),
        "timing": response.timing.model_dump(),
        "artifacts": public_artifacts,
    }
    return ToolResult(
        facts=facts,
        confidence=0.0,
        warnings=warnings,
        overlay=Overlay(type=OverlayType.CHANGE_MASK, file=public_artifacts["overlay"]),
    )


def _looks_like_path(value: str) -> bool:
    return bool(re.search(r"(?:[A-Za-z]:[\\/]|(?:^|\s)/)", value))
