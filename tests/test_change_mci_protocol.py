"""The main SatQuery environment may import the shared MCI contract without Torch."""

import sys
import unittest
import uuid
from math import inf, nan

from pydantic import ValidationError


class ChangeMciProtocolTest(unittest.TestCase):
    def test_shared_mci_protocol_does_not_import_torch(self) -> None:
        from satquery.tools.change_mci_protocol import HealthResponse

        self.assertEqual(
            HealthResponse().model_dump(),
            {
                "status": "ok",
                "service": "satquery-mci-worker",
                "contract_version": "1.0",
            },
        )
        self.assertNotIn("torch", sys.modules)

    def test_request_contract_rejects_wrong_version_and_invalid_uuid(self) -> None:
        from satquery.tools.change_mci_protocol import ChangeAnalysisRequest

        with self.assertRaises(ValidationError):
            ChangeAnalysisRequest(
                contract_version="9.9",
                request_id="not-a-uuid",
                before_path="C:/server/before.png",
                after_path="C:/server/after.png",
            )

        request = ChangeAnalysisRequest(
            contract_version="1.0",
            request_id=uuid.uuid4(),
            before_path="C:/server/before.png",
            after_path="C:/server/after.png",
        )
        self.assertEqual(request.contract_version, "1.0")

    def test_artifact_contract_rejects_an_absolute_path(self) -> None:
        from satquery.tools.change_mci_protocol import ArtifactFilenames

        with self.assertRaises(ValidationError):
            ArtifactFilenames(
                semantic_mask="semantic_mask_raw.png",
                semantic_mask_rgb="semantic_mask_rgb.png",
                binary_mask="change_binary_mask.png",
                overlay="C:/private/overlay.png",
                components="components.json",
            )

    def test_request_rejects_missing_paths_relative_paths_bad_geo_and_unknown_fields(self) -> None:
        from satquery.tools.change_mci_protocol import ChangeAnalysisRequest

        valid = {
            "contract_version": "1.0",
            "request_id": str(uuid.uuid4()),
            "before_path": "C:/server/before.tif",
            "after_path": "C:/server/after.tif",
        }
        for invalid in (
            {key: value for key, value in valid.items() if key != "contract_version"},
            {key: value for key, value in valid.items() if key != "before_path"},
            {key: value for key, value in valid.items() if key != "after_path"},
            {**valid, "before_path": "relative.tif"},
            {**valid, "after_path": ""},
            {**valid, "geo_metadata": ["not", "an", "object"]},
            {**valid, "client_selected_run_id": "forbidden"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    ChangeAnalysisRequest(**invalid)

    def test_artifact_contract_rejects_traversal_and_separators(self) -> None:
        from satquery.tools.change_mci_protocol import ArtifactFilenames

        base = {
            "semantic_mask": "semantic_mask_raw.png",
            "semantic_mask_rgb": "semantic_mask_rgb.png",
            "binary_mask": "change_binary_mask.png",
            "overlay": "overlay.png",
            "components": "components.json",
        }
        for value in ("../overlay.png", "nested/overlay.png", "nested\\overlay.png"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    ArtifactFilenames(**{**base, "overlay": value})

    def test_statistics_rejects_nonfinite_and_inconsistent_counts(self) -> None:
        from satquery.tools.change_mci_protocol import StatisticsResponse

        valid = {
            "total_pixels": 100,
            "valid_pixels": 100,
            "unchanged_pixels": 80,
            "changed_pixels": 20,
            "changed_fraction": 0.2,
            "changed_percent": 20.0,
            "per_class": {},
        }
        for invalid in (
            {**valid, "changed_pixels": 101},
            {**valid, "changed_fraction": 1.1},
            {**valid, "changed_percent": 101.0},
            {**valid, "changed_percent": nan},
            {**valid, "changed_percent": inf},
            {**valid, "unchanged_pixels": -1},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    StatisticsResponse(**invalid)

    def test_success_and_error_contracts_reject_malformed_payloads(self) -> None:
        from satquery.tools.change_mci_protocol import (
            ChangeAnalysisErrorResponse,
            ChangeAnalysisSuccessResponse,
        )

        with self.assertRaises(ValidationError):
            ChangeAnalysisSuccessResponse(
                contract_version="1.0",
                request_id=uuid.uuid4(),
                run_id="not-a-run-id",
            )
        with self.assertRaises(ValidationError):
            ChangeAnalysisErrorResponse(
                error={"code": "PRIVATE_EXCEPTION", "message": "do not expose", "retryable": False}
            )

    def test_main_side_client_and_adapter_do_not_import_mci_runtime(self) -> None:
        import satquery.tools.change_mci
        import satquery.tools.mci_worker_client

        forbidden = [name for name in sys.modules if name == "torch" or name.startswith("experiments.tool2_mci")]
        self.assertEqual(forbidden, [])
