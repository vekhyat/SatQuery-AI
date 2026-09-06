"""Stable, JSON-friendly boundary for the team checker and query router.

The backend owns paths and configuration. Never pass LLM-selected filesystem
paths directly here; resolve uploaded assets in the team's checker first.
"""
from dataclasses import fields
from pathlib import Path

import rasterio

from .inputs import DatasetError, local_path, parse_manifest
from .pipeline import Config, check_dataset, run_pipeline

CONTRACT_VERSION = "1.0"
TOOL_NAME = "optical_sar_v1"
EXPECTED_ERRORS = (DatasetError, OSError, rasterio.errors.RasterioError, MemoryError)


def rejection(reason, code="invalid_dataset"):
    """Handbook-compatible failure. No result files are advertised on rejection."""
    return {"task": "reject", "tools": ["checker_v1"], "parameters": {}, "facts": {},
            "answer_text": reason, "confidence": 0.0, "warnings": [],
            "overlay": {"type": "none", "file": None}, "layers": {},
            "receipt": {"why_this_tool": "Tool 3 input/configuration validation failed",
                        "rejected": True, "reason": reason, "error_code": code}}


def error_result(exc):
    if isinstance(exc, MemoryError):
        return rejection("Insufficient memory; crop the scene or lower its resolution.", "resource_limit")
    return rejection(str(exc) or "Unable to process the supplied scene.")


def prepare_request(request, *, base_dir):
    """Return validated BandSource mapping and Config without reading pixels.

This validates the request structure; use check_tool3_request for header checks.
Unknown fields and nonfinite/bool numeric settings are rejected by the runtime.
"""
    sources, parameters = parse_manifest(request, base_dir)
    allowed = {field.name for field in fields(Config)}
    if set(parameters) - allowed:
        raise DatasetError("Unknown parameters: " + ", ".join(sorted(str(k) for k in set(parameters) - allowed)))
    return sources, Config(**parameters)


def check_tool3_request(request, *, base_dir):
    """M3 preflight: metadata_valid result or the shared rejection envelope.

The metadata result is a checker diagnostic, not a completed tool result.
It cannot certify pixel overlap or prediction accuracy.
"""
    try:
        sources, config = prepare_request(request, base_dir=base_dir)
        return check_dataset(sources, config)
    except EXPECTED_ERRORS as exc:
        return error_result(exc)


def optical_sar_v1(request, *, base_dir, output_dir):
    """M1 registry entry: manifest-shaped dict -> complete handbook envelope.

Synchronous CPU/I/O work; call in a worker/thread, not on an async event loop.
Every successful invocation writes a unique run and returns its own paths.
Expected data/I/O failures return task='reject'; programming bugs still raise.
"""
    try:
        if not isinstance(output_dir, (str, Path)) or not str(output_dir).strip():
            raise DatasetError("output_dir must be a nonempty local directory path.")
        sources, config = prepare_request(request, base_dir=base_dir)
        return run_pipeline(sources, local_path(output_dir), config)
    except EXPECTED_ERRORS as exc:
        return error_result(exc)
