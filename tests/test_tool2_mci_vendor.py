import importlib.util
import unittest
from pathlib import Path


class MCIVendorBoundaryTest(unittest.TestCase):
    def test_isolated_vendor_package_and_vocabulary_are_available(self):
        package_name = "experiments.tool2_mci.vendor.change_agent_mci"
        try:
            spec = importlib.util.find_spec(package_name)
        except ModuleNotFoundError:
            spec = None
        self.assertIsNotNone(
            spec,
            "The Tool 2 runtime must provide its own isolated Change-Agent MCI package",
        )

        from experiments.tool2_mci.vendor.change_agent_mci import VOCAB_PATH
        from experiments.tool2_mci.mci_inference import load_and_validate_vocab

        self.assertTrue(Path(VOCAB_PATH).is_file())
        vocab = load_and_validate_vocab(VOCAB_PATH)
        self.assertEqual(len(vocab), 468)
        self.assertEqual(sorted(vocab.values()), list(range(468)))

    def test_runtime_resolves_model_classes_from_isolated_vendor(self):
        from experiments.tool2_mci import mci_inference

        self.assertTrue(
            hasattr(mci_inference, "load_model_classes"),
            "Runtime needs an explicit vendored model-class boundary",
        )
        encoder, attentive_encoder, decoder = mci_inference.load_model_classes()
        for model_class in (encoder, attentive_encoder, decoder):
            self.assertTrue(
                model_class.__module__.startswith(
                    "experiments.tool2_mci.vendor.change_agent_mci."
                )
            )


if __name__ == "__main__":
    unittest.main()
