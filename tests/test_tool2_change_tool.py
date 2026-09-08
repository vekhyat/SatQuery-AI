import importlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from experiments.tool2_mci.mci_inference import MCIPrediction


try:
    tool_module = importlib.import_module("experiments.tool2_mci.change_analysis_tool")
except ImportError:
    tool_module = None


class FakeMCIRuntime:
    def __init__(self, checkpoint_path: Path, mask: np.ndarray):
        self.checkpoint_path = checkpoint_path
        self.device = "cpu"
        self.load_status = {
            "encoder_dict": {"missing_keys": [], "unexpected_keys": []},
            "encoder_trans_dict": {"missing_keys": [], "unexpected_keys": ["legacy.weight"]},
            "decoder_dict": {"missing_keys": [], "unexpected_keys": []},
        }
        self._mask = mask

    def predict(self, before_path: Path, after_path: Path) -> MCIPrediction:
        return MCIPrediction(
            caption="an exact model caption",
            mask=self._mask.copy(),
            inference_seconds=0.25,
        )


class ChangeAnalysisToolBoundaryTest(unittest.TestCase):
    def test_change_analysis_tool_is_available(self):
        self.assertIsNotNone(tool_module, "ChangeAnalysisTool is not implemented")
        self.assertTrue(callable(getattr(tool_module, "ChangeAnalysisTool", None)))


@unittest.skipIf(tool_module is None, "ChangeAnalysisTool is not implemented")
class ChangeAnalysisToolTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.before = self.root / "source_before.png"
        self.after = self.root / "source_after.png"
        Image.new("RGB", (2, 2), color=(10, 20, 30)).save(self.before)
        Image.new("RGB", (2, 2), color=(40, 50, 60)).save(self.after)
        self.checkpoint = self.root / "model.pth"
        self.checkpoint.write_bytes(b"checkpoint fixture")
        self.mask = np.array([[0, 1], [2, 0]], dtype=np.uint8)
        self.runtime = FakeMCIRuntime(self.checkpoint, self.mask)
        self.tool = tool_module.ChangeAnalysisTool(
            self.runtime,
            component_min_pixels=1,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_result_preserves_caption_question_and_confidence_provenance(self):
        result = self.tool.analyze(
            self.before,
            self.after,
            question="What changed?",
            output_dir=self.root / "outputs",
            job_id="case",
        )
        payload = result.to_dict()

        self.assertEqual(payload["task"], "change_analysis")
        self.assertEqual(payload["input"]["question"], "What changed?")
        self.assertFalse(payload["input"]["geospatial_metadata_available"])
        self.assertEqual(payload["facts"]["summary"], "an exact model caption")
        self.assertEqual(
            payload["facts"]["caption"],
            {
                "text": "an exact model caption",
                "source": "Change-Agent MCI decoder",
                "question_conditioned": False,
            },
        )
        self.assertEqual(payload["confidence"]["score"], None)
        self.assertEqual(payload["confidence"]["type"], "unavailable")
        self.assertEqual(
            payload["confidence"]["source"],
            "model_does_not_expose_calibrated_confidence",
        )
        self.assertTrue(any("context only" in warning for warning in payload["warnings"]))

    def test_statistics_geospatial_nulls_and_json_are_serialized(self):
        result = self.tool.analyze(
            self.before,
            self.after,
            output_dir=self.root / "outputs",
            job_id="stats",
        )
        payload = result.to_dict()
        facts = payload["facts"]

        self.assertEqual(facts["total_pixels"], 4)
        self.assertEqual(facts["valid_pixels"], 4)
        self.assertEqual(facts["changed_pixels"], 2)
        self.assertEqual(facts["changed_fraction"], 0.5)
        self.assertEqual(facts["changed_percent"], 50.0)
        self.assertIsNone(facts["physical_area_m2"])
        self.assertIsNone(facts["physical_area_hectares"])
        self.assertIsNone(facts["coordinates"])
        self.assertTrue(any("validated geospatial transform" in item for item in payload["warnings"]))

        result_path = Path(payload["evidence"]["result"])
        self.assertEqual(json.loads(result_path.read_text(encoding="utf-8")), payload)

    def test_artifacts_are_aligned_and_use_required_palette(self):
        result = self.tool.analyze(
            self.before,
            self.after,
            output_dir=self.root / "outputs",
            job_id="artifacts",
        )
        evidence = result.to_dict()["evidence"]
        expected_names = {
            "before": "before.png",
            "after": "after.png",
            "semantic_mask": "semantic_mask_raw.png",
            "semantic_mask_rgb": "semantic_mask_rgb.png",
            "binary_mask": "change_binary_mask.png",
            "overlay": "overlay.png",
            "components": "components.json",
            "result": "result.json",
        }
        for key, filename in expected_names.items():
            path = Path(evidence[key])
            self.assertTrue(path.is_absolute())
            self.assertEqual(path.name, filename)
            self.assertTrue(path.is_file())

        for key in ("before", "after", "semantic_mask", "semantic_mask_rgb", "binary_mask", "overlay"):
            with Image.open(evidence[key]) as image:
                self.assertEqual(image.size, (2, 2))

        rgb = np.asarray(Image.open(evidence["semantic_mask_rgb"]))
        colors = {tuple(color) for color in rgb.reshape(-1, 3).tolist()}
        self.assertEqual(colors, {(0, 0, 0), (255, 255, 0), (255, 0, 0)})
        binary = np.asarray(Image.open(evidence["binary_mask"]))
        self.assertEqual(set(np.unique(binary).tolist()), {0, 255})

    def test_repeated_job_id_creates_unique_output_directories(self):
        first = self.tool.analyze(
            self.before,
            self.after,
            output_dir=self.root / "outputs",
            job_id="same job",
        )
        second = self.tool.analyze(
            self.before,
            self.after,
            output_dir=self.root / "outputs",
            job_id="same job",
        )
        first_dir = Path(first.to_dict()["evidence"]["result"]).parent
        second_dir = Path(second.to_dict()["evidence"]["result"]).parent
        self.assertNotEqual(first_dir, second_dir)
        self.assertTrue(first_dir.is_dir())
        self.assertTrue(second_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
