"""Evidence artifact creation for standalone Tool 2 analyses."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .mci_inference import create_overlay, visualize_mask


def create_unique_output_directory(output_root: str | Path, job_id: str | None) -> Path:
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    source_name = job_id.strip() if job_id and job_id.strip() else f"analysis-{uuid.uuid4().hex[:12]}"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source_name).strip(".-_")
    if not safe_name:
        safe_name = f"analysis-{uuid.uuid4().hex[:12]}"

    candidate = root / safe_name
    try:
        candidate.mkdir(exist_ok=False)
        return candidate
    except FileExistsError:
        while True:
            candidate = root / f"{safe_name}-{uuid.uuid4().hex[:8]}"
            try:
                candidate.mkdir(exist_ok=False)
                return candidate
            except FileExistsError:
                continue


def write_evidence_artifacts(
    analysis_dir: str | Path,
    before_path: str | Path,
    after_path: str | Path,
    semantic_mask: np.ndarray,
    components: dict[str, Any],
    overlay_alpha: float,
) -> dict[str, str]:
    target = Path(analysis_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    mask = np.asarray(semantic_mask, dtype=np.uint8)

    with Image.open(before_path) as before_source:
        before = before_source.convert("RGB")
    with Image.open(after_path) as after_source:
        after = after_source.convert("RGB")
    if before.size != after.size:
        raise ValueError("Before and after artifact dimensions must match")
    if mask.shape != (after.height, after.width):
        raise ValueError("Semantic mask dimensions must match the input images")

    paths = {
        "before": target / "before.png",
        "after": target / "after.png",
        "semantic_mask": target / "semantic_mask_raw.png",
        "semantic_mask_rgb": target / "semantic_mask_rgb.png",
        "binary_mask": target / "change_binary_mask.png",
        "overlay": target / "overlay.png",
        "components": target / "components.json",
        "result": target / "result.json",
    }
    before.save(paths["before"])
    after.save(paths["after"])

    rgb_mask = visualize_mask(mask)
    binary_mask = np.where(mask != 0, 255, 0).astype(np.uint8)
    overlay = create_overlay(np.asarray(after), rgb_mask, alpha=overlay_alpha)
    Image.fromarray(mask, mode="L").save(paths["semantic_mask"])
    Image.fromarray(rgb_mask, mode="RGB").save(paths["semantic_mask_rgb"])
    Image.fromarray(binary_mask, mode="L").save(paths["binary_mask"])
    Image.fromarray(overlay, mode="RGB").save(paths["overlay"])
    paths["components"].write_text(
        json.dumps(components, indent=2) + "\n",
        encoding="utf-8",
    )
    return {name: str(path.resolve()) for name, path in paths.items()}
