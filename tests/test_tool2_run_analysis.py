import importlib
import tempfile
import unittest
from pathlib import Path


try:
    runner = importlib.import_module("experiments.tool2_mci.run_analysis")
except ImportError:
    runner = None


class RunAnalysisBoundaryTest(unittest.TestCase):
    def test_runner_is_available(self):
        self.assertIsNotNone(runner, "The two-sample analysis runner is not implemented")
        self.assertTrue(callable(getattr(runner, "select_sample_names", None)))


@unittest.skipIf(runner is None, "analysis runner is not implemented")
class DeterministicSampleSelectionTest(unittest.TestCase):
    def test_selects_baseline_and_next_lexicographic_matching_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_root = Path(temp_dir)
            a_dir = test_root / "A"
            b_dir = test_root / "B"
            a_dir.mkdir()
            b_dir.mkdir()
            for name in ("test_000003.png", "test_000004.png", "test_000005.png", "test_000006.png"):
                (a_dir / name).touch()
            for name in ("test_000003.png", "test_000004.png", "test_000005.png", "test_000007.png"):
                (b_dir / name).touch()

            selected = runner.select_sample_names(test_root, "test_000004.png")
            self.assertEqual(selected, ["test_000004.png", "test_000005.png"])

    def test_missing_baseline_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_root = Path(temp_dir)
            (test_root / "A").mkdir()
            (test_root / "B").mkdir()
            with self.assertRaisesRegex(ValueError, "matching A/B pair"):
                runner.select_sample_names(test_root, "test_000004.png")


if __name__ == "__main__":
    unittest.main()
