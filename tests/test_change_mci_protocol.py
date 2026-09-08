"""The main SatQuery environment may import the shared MCI contract without Torch."""

import sys
import unittest
import uuid

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
                before="before.png",
                after="after.png",
                semantic_mask="semantic_mask_raw.png",
                semantic_mask_rgb="semantic_mask_rgb.png",
                binary_mask="change_binary_mask.png",
                overlay="C:/private/overlay.png",
                components="components.json",
                result="result.json",
            )
