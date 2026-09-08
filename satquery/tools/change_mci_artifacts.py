"""Secure public access checks for completed Tool 2 evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

from satquery.errors import SatQueryError
from satquery.tools.context import ToolContext


RUN_ID_PATTERN = re.compile(r"[a-f0-9]{32}\Z")
PUBLIC_ARTIFACTS = {
    "semantic_mask_raw.png": ("semantic_mask", "image/png"),
    "semantic_mask_rgb.png": ("semantic_mask_rgb", "image/png"),
    "change_binary_mask.png": ("binary_mask", "image/png"),
    "overlay.png": ("overlay", "image/png"),
    "components.json": ("components", "application/json"),
}


def artifact_path(context: ToolContext, run_id: str, filename: str) -> Path:
    """Return one public evidence file only when its provenance is still valid."""

    try:
        if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid run id")
        if not isinstance(filename, str) or filename not in PUBLIC_ARTIFACTS:
            raise ValueError("invalid artifact name")

        root = context.output_dir.resolve()
        run_directory = (root / run_id).resolve(strict=True)
        if not run_directory.is_dir() or run_directory.parent != root:
            raise ValueError("invalid run directory")

        artifact = _contained_file(run_directory / filename, run_directory)
        result_path = _contained_file(run_directory / "result.json", run_directory)
        result = _read_object(result_path)
        _validate_completed_result(result, result_path, artifact, filename)

        access_path = _contained_file(run_directory / "access.json", run_directory)
        asset_ids = _validate_access_manifest(_read_object(access_path), run_id)
        for asset_id in asset_ids:
            context.store.load(asset_id)
        return artifact
    except (OSError, ValueError, TypeError, json.JSONDecodeError, SatQueryError) as error:
        raise SatQueryError(
            404,
            "tool2_artifact_not_found",
            "The change-analysis artifact is unavailable or its source assets have expired.",
        ) from error


def media_type(filename: str) -> str:
    """Return the fixed media type for an allowlisted public filename."""

    return PUBLIC_ARTIFACTS[filename][1]


def _contained_file(candidate: Path, run_directory: Path) -> Path:
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or resolved.parent != run_directory:
        raise ValueError("artifact escaped run directory")
    return resolved


def _read_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be an object")
    return payload


def _validate_completed_result(
    result: dict[str, object],
    result_path: Path,
    artifact_path: Path,
    filename: str,
) -> None:
    if result.get("task") != "change_analysis":
        raise ValueError("result is not a completed change analysis")
    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("result has no evidence")
    if not _matches_path(evidence.get("result"), result_path):
        raise ValueError("result does not advertise itself")
    evidence_key = PUBLIC_ARTIFACTS[filename][0]
    if not _matches_path(evidence.get(evidence_key), artifact_path):
        raise ValueError("artifact was not advertised by completed result")


def _matches_path(value: object, expected: Path) -> bool:
    if not isinstance(value, str):
        return False
    candidate = Path(value)
    try:
        return candidate.is_absolute() and candidate.resolve(strict=True) == expected
    except OSError:
        return False


def _validate_access_manifest(manifest: dict[str, object], run_id: str) -> list[UUID]:
    if set(manifest) != {"asset_ids", "run_id", "tool"}:
        raise ValueError("unexpected access manifest shape")
    if manifest["run_id"] != run_id or manifest["tool"] != "change_mci_v1":
        raise ValueError("access manifest does not match run")
    raw_asset_ids = manifest["asset_ids"]
    if not isinstance(raw_asset_ids, list) or len(raw_asset_ids) != 2:
        raise ValueError("access manifest must name two source assets")
    asset_ids: list[UUID] = []
    for raw_asset_id in raw_asset_ids:
        if not isinstance(raw_asset_id, str):
            raise ValueError("asset id must be a string")
        asset_id = UUID(raw_asset_id)
        if str(asset_id) != raw_asset_id:
            raise ValueError("asset id is not canonical")
        asset_ids.append(asset_id)
    if asset_ids[0] == asset_ids[1]:
        raise ValueError("source assets must be distinct")
    return asset_ids
