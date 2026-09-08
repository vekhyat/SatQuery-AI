import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from experiments.tool2_mci.change_analysis_tool import ChangeAnalysisTool
from experiments.tool2_mci.mci_inference import MCIInference


@unittest.skipUnless(
    os.environ.get("RUN_MCI_CHECKPOINT_TEST") == "1",
    "Set RUN_MCI_CHECKPOINT_TEST=1 for the expensive official-checkpoint regression",
)
class FrozenMCICheckpointRegressionTest(unittest.TestCase):
    def test_test_000004_matches_phase1_caption_counts_and_mask(self):
        root = Path(__file__).resolve().parents[1]
        test_root = root / "LEVIR-MCI-dataset" / "images" / "test"
        runtime = MCIInference(root / "MCI_model.pth", device="cuda:0")
        tool = ChangeAnalysisTool(runtime)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = tool.analyze(
                test_root / "A" / "test_000004.png",
                test_root / "B" / "test_000004.png",
                output_dir=temp_dir,
                job_id="regression",
            )
            payload = result.to_dict()
            actual_mask = np.asarray(Image.open(payload["evidence"]["semantic_mask"]))

        frozen_mask = np.asarray(
            Image.open(
                root
                / "outputs"
                / "tool2_mci_smoke"
                / "test_000004"
                / "predicted_mask_raw.png"
            )
        )
        self.assertEqual(
            payload["facts"]["caption"]["text"],
            "the vegetation has been removed and a road with villas built along appears",
        )
        classes = payload["facts"]["classes"]
        self.assertEqual(classes["unchanged_background"]["pixel_count"], 45598)
        self.assertEqual(classes["road_change"]["pixel_count"], 7382)
        self.assertEqual(classes["building_change"]["pixel_count"], 12556)
        self.assertEqual(payload["facts"]["changed_pixels"], 19938)
        np.testing.assert_array_equal(actual_mask, frozen_mask)


if __name__ == "__main__":
    unittest.main()
