"""Run frozen-baseline and next-pair Tool 2 analyses with one MCI model load."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .change_analysis_tool import ChangeAnalysisTool
from .mci_inference import MCIInference


FROZEN_SAMPLE = "test_000004.png"
FROZEN_CAPTION = (
    "the vegetation has been removed and a road with villas built along appears"
)
FROZEN_COUNTS = {
    "unchanged_background": 45598,
    "road_change": 7382,
    "building_change": 12556,
}
FROZEN_CHANGED_PIXELS = 19938


def select_sample_names(test_root: str | Path, baseline_name: str) -> list[str]:
    root = Path(test_root).resolve()
    a_names = {path.name for path in (root / "A").glob("*.png") if path.is_file()}
    b_names = {path.name for path in (root / "B").glob("*.png") if path.is_file()}
    matching = sorted(a_names & b_names)
    if baseline_name not in matching:
        raise ValueError(f"Baseline {baseline_name!r} is not a matching A/B pair")
    baseline_index = matching.index(baseline_name)
    if baseline_index + 1 >= len(matching):
        raise ValueError(f"No lexicographic matching A/B pair follows {baseline_name!r}")
    return [baseline_name, matching[baseline_index + 1]]


def verify_frozen_baseline(payload: dict, frozen_mask_path: str | Path) -> None:
    facts = payload["facts"]
    if facts["caption"]["text"] != FROZEN_CAPTION:
        raise RuntimeError("Frozen MCI caption regression failed")
    actual_counts = {
        name: facts["classes"][name]["pixel_count"] for name in FROZEN_COUNTS
    }
    if actual_counts != FROZEN_COUNTS:
        raise RuntimeError(
            f"Frozen MCI class-count regression failed: {actual_counts!r}"
        )
    if facts["changed_pixels"] != FROZEN_CHANGED_PIXELS:
        raise RuntimeError("Frozen MCI changed-pixel regression failed")

    with Image.open(payload["evidence"]["semantic_mask"]) as actual_image:
        actual_mask = np.asarray(actual_image)
    with Image.open(frozen_mask_path) as frozen_image:
        frozen_mask = np.asarray(frozen_image)
    if not np.array_equal(actual_mask, frozen_mask):
        raise RuntimeError("Frozen MCI semantic-mask regression failed")


def main() -> None:
    workspace_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=workspace_root / "MCI_model.pth",
    )
    parser.add_argument(
        "--test-root",
        type=Path,
        default=workspace_root / "LEVIR-MCI-dataset" / "images" / "test",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=workspace_root / "outputs" / "tool2",
    )
    parser.add_argument("--baseline", default=FROZEN_SAMPLE)
    parser.add_argument("--device", default=None)
    parser.add_argument("--question", default=None)
    parser.add_argument("--component-min-pixels", type=int, default=6)
    args = parser.parse_args()

    sample_names = select_sample_names(args.test_root, args.baseline)
    runtime = MCIInference(args.checkpoint, device=args.device)
    tool = ChangeAnalysisTool(
        runtime,
        component_min_pixels=args.component_min_pixels,
        default_output_root=args.output_root,
    )

    summaries = []
    for sample_name in sample_names:
        result = tool.analyze(
            args.test_root / "A" / sample_name,
            args.test_root / "B" / sample_name,
            question=args.question,
            job_id=Path(sample_name).stem,
        )
        payload = result.to_dict()
        if sample_name == args.baseline:
            verify_frozen_baseline(
                payload,
                workspace_root
                / "outputs"
                / "tool2_mci_smoke"
                / "test_000004"
                / "predicted_mask_raw.png",
            )
        summaries.append(
            {
                "sample": sample_name,
                "caption": payload["facts"]["caption"]["text"],
                "class_pixel_counts": {
                    str(item["class_id"]): item["pixel_count"]
                    for item in payload["facts"]["classes"].values()
                },
                "changed_pixels": payload["facts"]["changed_pixels"],
                "changed_percent": payload["facts"]["changed_percent"],
                "result_path": payload["evidence"]["result"],
            }
        )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
