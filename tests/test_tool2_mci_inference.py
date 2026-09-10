import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from experiments.tool2_mci.mci_inference import (
    CLASS_COLORS,
    compute_binary_metrics,
    decode_caption,
    preprocess_image,
    summarize_mask,
    visualize_mask,
)


_HAS_TORCH = importlib.util.find_spec("torch") is not None


class MCIInferenceHelpersTest(unittest.TestCase):
    @unittest.skipUnless(_HAS_TORCH, "tensor preprocessing requires torch in the worker environment")
    def test_preprocess_uses_research_normalization(self):
        pixels = np.zeros((256, 256, 3), dtype=np.uint8)
        pixels[:, :, 0] = 100
        pixels[:, :, 1] = 110
        pixels[:, :, 2] = 120

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rgb.png"
            Image.fromarray(pixels, mode="RGB").save(path)
            tensor = preprocess_image(path)

        self.assertEqual(tuple(tensor.shape), (1, 3, 256, 256))
        expected = pixels.astype(np.float32).transpose(2, 0, 1)
        mean = [0.39073 * 255, 0.38623 * 255, 0.32989 * 255]
        std = [0.15329 * 255, 0.14628 * 255, 0.13648 * 255]
        for channel in range(3):
            expected[channel, :, :] -= mean[channel]
            expected[channel, :, :] /= std[channel]
        np.testing.assert_array_equal(tensor.numpy()[0], expected)

    @unittest.skipUnless(_HAS_TORCH, "tensor preprocessing requires torch in the worker environment")
    def test_preprocess_rejects_non_256_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "small.png"
            Image.new("RGB", (128, 128)).save(path)
            with self.assertRaisesRegex(ValueError, "256x256"):
                preprocess_image(path)

    def test_caption_decoding_uses_ids_not_json_key_order(self):
        vocab = {"road": 4, "<END>": 2, "<NULL>": 0, "<START>": 1, "change": 5}
        self.assertEqual(decode_caption([1, 4, 5, 2, 0], vocab), "road change")

    def test_mask_summary_and_rgb_palette(self):
        mask = np.array([[0, 1], [2, 2]], dtype=np.uint8)
        summary = summarize_mask(mask)
        self.assertEqual(summary["mask_shape"], [2, 2])
        self.assertEqual(summary["unique_classes"], [0, 1, 2])
        self.assertEqual(summary["class_pixel_counts"], {"0": 1, "1": 1, "2": 2})
        self.assertEqual(summary["changed_pixels"], 3)
        self.assertAlmostEqual(summary["changed_percent"], 75.0)

        rgb = visualize_mask(mask)
        np.testing.assert_array_equal(rgb[0, 0], CLASS_COLORS[0])
        np.testing.assert_array_equal(rgb[0, 1], CLASS_COLORS[1])
        np.testing.assert_array_equal(rgb[1, 0], CLASS_COLORS[2])

    def test_binary_metrics(self):
        prediction = np.array([[0, 1], [2, 0]], dtype=np.uint8)
        ground_truth = np.array([[0, 2], [0, 0]], dtype=np.uint8)
        metrics = compute_binary_metrics(prediction, ground_truth)
        self.assertAlmostEqual(metrics["changed_iou"], 0.5)
        self.assertAlmostEqual(metrics["precision"], 0.5)
        self.assertAlmostEqual(metrics["recall"], 1.0)
        self.assertAlmostEqual(metrics["f1"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
