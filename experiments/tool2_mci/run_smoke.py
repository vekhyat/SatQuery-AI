"""Run one deterministic LEVIR-MCI pair through the pretrained MCI model."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from experiments.tool2_mci.mci_inference import (
    MCIInference,
    compute_binary_metrics,
    create_overlay,
    summarize_mask,
    visualize_mask,
)


def _load_ground_truth(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        array = np.asarray(image)
    if array.ndim == 3:
        return np.any(array != 0, axis=2).astype(np.uint8)
    return (array != 0).astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        default="test_000004.png",
        help="Matching filename in LEVIR-MCI test/A and test/B",
    )
    parser.add_argument("--device", default=None, help="Explicit torch device, e.g. cuda:0 or cpu")
    args = parser.parse_args()

    workspace_root = Path(__file__).resolve().parents[2]
    test_root = workspace_root / "LEVIR-MCI-dataset" / "images" / "test"
    image_a_path = (test_root / "A" / args.sample).resolve()
    image_b_path = (test_root / "B" / args.sample).resolve()
    ground_truth_path = (test_root / "label" / args.sample).resolve()
    for path in (image_a_path, image_b_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    checkpoint_path = (workspace_root / "MCI_model.pth").resolve()
    output_dir = (
        workspace_root / "outputs" / "tool2_mci_smoke" / Path(args.sample).stem
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    runtime = MCIInference(
        checkpoint_path=checkpoint_path,
        device=args.device,
    )
    prediction = runtime.predict(image_a_path, image_b_path)
    stats = summarize_mask(prediction.mask)

    before_output = output_dir / "before.png"
    after_output = output_dir / "after.png"
    raw_mask_output = output_dir / "predicted_mask_raw.png"
    rgb_mask_output = output_dir / "predicted_mask_rgb.png"
    overlay_output = output_dir / "overlay.png"
    result_output = output_dir / "result.json"

    shutil.copy2(image_a_path, before_output)
    shutil.copy2(image_b_path, after_output)
    mask_rgb = visualize_mask(prediction.mask)
    Image.fromarray(prediction.mask, mode="L").save(raw_mask_output)
    Image.fromarray(mask_rgb, mode="RGB").save(rgb_mask_output)
    with Image.open(image_b_path) as image_b:
        overlay = create_overlay(np.asarray(image_b.convert("RGB")), mask_rgb)
    Image.fromarray(overlay, mode="RGB").save(overlay_output)

    result = {
        "caption": prediction.caption,
        **stats,
        "inference_seconds": prediction.inference_seconds,
        "class_meanings": {"0": "unchanged/background", "1": "road change", "2": "building change"},
        "device": str(runtime.device),
        "checkpoint_load_status": runtime.load_status,
        "sample": {
            "before": str(image_a_path),
            "after": str(image_b_path),
        },
    }

    if ground_truth_path.is_file():
        ground_truth = _load_ground_truth(ground_truth_path)
        result["sample"]["ground_truth"] = str(ground_truth_path)
        result["sanity_metrics"] = compute_binary_metrics(prediction.mask, ground_truth)

    result_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print("outputs:")
    for path in (
        before_output,
        after_output,
        raw_mask_output,
        rgb_mask_output,
        overlay_output,
        result_output,
    ):
        print(path)


if __name__ == "__main__":
    main()
