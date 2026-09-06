"""Convert backend result paths to frontend URLs without exposing source paths."""
from copy import deepcopy
from pathlib import Path
import re
from urllib.parse import urlsplit

from .contracts import rejection
from .inputs import DatasetError, read_json

RUN_PATTERN = re.compile(r"[0-9]{8}T[0-9]{6}_[0-9a-f]{8}\Z")
MAPS = ("optical_only", "sar_only", "fused")
ARTIFACTS = frozenset(
    [f"{name}.{ext}" for name in MAPS for ext in ("png", "tif")]
    + [f"{sensor}_{kind}_mask.{ext}" for sensor in ("optical", "sar", "fused")
       for kind in ("water", "builtup") for ext in ("png", "tif")]
    + ["ndwi.tif", "ndbi.tif", "ndvi.tif", "sar_vv_db.tif", "sar_vh_db.tif",
       "optical_preview.png", "sar_preview.png"]
)


def resolve_artifact(output_dir, run_id, filename):
    """Only completed runs and known PNG/TIFF artifacts can be served.

The HTTP owner must enforce per-user authorization before calling this helper.
Private result.json and report.html deliberately are not HTTP artifacts.
"""
    if not isinstance(run_id, str) or not RUN_PATTERN.fullmatch(run_id) or not isinstance(filename, str) or filename not in ARTIFACTS:
        raise DatasetError("Unknown artifact.")
    root = Path(output_dir).expanduser().resolve()
    run = root / run_id
    if run.resolve().parent != root:
        raise DatasetError("Unknown artifact.")
    manifest = run / "result.json"
    if not manifest.is_file() or manifest.resolve().parent != run:
        raise DatasetError("Run is not complete.")
    result = read_json(manifest)
    if result.get("receipt", {}).get("rejected", True) or result.get("receipt", {}).get("run_id") != run_id:
        raise DatasetError("Run is not complete.")
    path = run / filename
    if filename not in result.get("receipt", {}).get("artifacts", []) or not path.is_file() or path.resolve().parent != run:
        raise DatasetError("Unknown artifact.")
    return path


def to_web_result(result, *, output_dir, artifact_base_url="/artifacts"):
    """Copy a successful result and replace layer/overlay paths with HTTP URLs.

Use trusted pipeline results. Failures are made generic at this HTTP boundary;
log the detailed original envelope on the backend for troubleshooting.
"""
    if result.get("task") == "reject":
        return rejection("Tool 3 could not process this dataset. Check the dataset configuration or server log.",
                         result.get("receipt", {}).get("error_code", "invalid_dataset"))
    if not isinstance(artifact_base_url, str):
        raise DatasetError("artifact_base_url must be a URL or root-relative path.")
    parts = urlsplit(artifact_base_url)
    if (parts.query or parts.fragment or "\\" in artifact_base_url or
            (parts.scheme and (parts.scheme not in ("http", "https") or not parts.netloc)) or
            (not parts.scheme and (not artifact_base_url.startswith("/") or parts.netloc))):
        raise DatasetError("artifact_base_url must be an HTTP(S) URL or root-relative path without query/fragment.")
    run_id = result["receipt"]["run_id"]
    root = Path(output_dir).expanduser().resolve()
    if Path(result["receipt"]["output_dir"]).resolve() != root / run_id:
        raise DatasetError("Result does not belong to this output directory.")
    links = {}
    for filename in result["receipt"]["artifacts"]:
        if filename in ARTIFACTS:
            resolve_artifact(root, run_id, filename)
            links[filename] = f"{artifact_base_url.rstrip('/')}/{run_id}/{filename}"
    result_copy = deepcopy(result)
    result_copy["layers"] = {name: links[f"{name}.png"] for name in MAPS}
    result_copy["overlay"] = {"type": "landcover_mask", "file": links["fused.tif"]}
    receipt_keys = ("software", "why_this_tool", "rejected", "reason", "run_id", "fusion_rule", "reference_grid", "preprocessing")
    result_copy["receipt"] = {key: deepcopy(result["receipt"][key]) for key in receipt_keys}
    result_copy["receipt"]["artifacts"] = links
    return result_copy
