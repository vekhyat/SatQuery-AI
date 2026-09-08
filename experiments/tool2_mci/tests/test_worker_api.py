"""Contract tests for the Tool 2 worker API using a checkpoint-free fake."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi.testclient")

from fastapi.testclient import TestClient
from PIL import Image

from experiments.tool2_mci.result import ConfidenceProvenance, Timing, Tool2Result
from experiments.tool2_mci.worker_api import (
    WorkerConfig,
    WorkerState,
    create_app,
)
from satquery.tools.change_mci_protocol import (
    CONTRACT_VERSION,
    ChangeAnalysisSuccessResponse,
)


class FakeChangeAnalyzer:
    """Creates the same result boundary as ChangeAnalysisTool without MCI/CUDA."""

    def __init__(
        self,
        *,
        wait_for_release: bool = False,
        fail: bool = False,
        outside_artifact: bool = False,
    ) -> None:
        self.wait_for_release = wait_for_release
        self.fail = fail
        self.outside_artifact = outside_artifact
        self.started = threading.Event()
        self.release = threading.Event()

    def analyze(
        self,
        before_path: Path,
        after_path: Path,
        *,
        geo_metadata: dict | None,
        output_dir: Path,
        job_id: str,
    ) -> Tool2Result:
        self.started.set()
        if self.wait_for_release:
            self.release.wait(timeout=2)
        if self.fail:
            raise RuntimeError("private checkpoint location must not escape")

        run_directory = output_dir / job_id
        run_directory.mkdir(parents=True, exist_ok=False)
        filenames = {
            "before": "before.png",
            "after": "after.png",
            "semantic_mask": "semantic_mask_raw.png",
            "semantic_mask_rgb": "semantic_mask_rgb.png",
            "binary_mask": "change_binary_mask.png",
            "overlay": "overlay.png",
            "components": "components.json",
            "result": "result.json",
        }
        for filename in filenames.values():
            (run_directory / filename).write_bytes(b"fake artifact")
        if self.outside_artifact:
            external = output_dir.parent / "outside-overlay.png"
            external.write_bytes(b"must not be returned")
            filenames["overlay"] = str(external)

        return Tool2Result(
            task="change_analysis",
            input={"before": str(before_path), "after": str(after_path)},
            model={
                "name": "Change-Agent MCI",
                "checkpoint_path": "C:/private/MCI_model.pth",
                "checkpoint_sha256": "a" * 64,
                "device": "cpu",
            },
            facts={
                "caption": {
                    "text": "two buildings were constructed",
                    "source": "Change-Agent MCI decoder",
                    "question_conditioned": False,
                },
                "total_pixels": 65536,
                "valid_pixels": 65536,
                "unchanged_pixels": 65000,
                "changed_pixels": 536,
                "changed_fraction": 0.0081787109375,
                "changed_percent": 0.81787109375,
                "classes": {
                    "unchanged_background": {
                        "class_id": 0,
                        "label": "unchanged/background",
                        "pixel_count": 65000,
                        "percent_of_valid_pixels": 99.18212890625,
                    },
                    "road_change": {
                        "class_id": 1,
                        "label": "road change",
                        "pixel_count": 36,
                        "percent_of_valid_pixels": 0.054931640625,
                        "percent_of_changed_pixels": 6.7164179104477615,
                    },
                    "building_change": {
                        "class_id": 2,
                        "label": "building change",
                        "pixel_count": 500,
                        "percent_of_valid_pixels": 0.762939453125,
                        "percent_of_changed_pixels": 93.28358208955224,
                    },
                },
                "components": {
                    "minimum_component_pixels": 6,
                    "connectivity": 8,
                    "all_changed": {
                        "raw_component_count": 2,
                        "filtered_component_count": 2,
                        "filtered_pixel_count": 536,
                        "largest_component_pixels": 500,
                        "items": [],
                    },
                    "road_change": {
                        "raw_component_count": 1,
                        "filtered_component_count": 1,
                        "filtered_pixel_count": 36,
                        "largest_component_pixels": 36,
                        "items": [],
                    },
                    "building_change": {
                        "raw_component_count": 1,
                        "filtered_component_count": 1,
                        "filtered_pixel_count": 500,
                        "largest_component_pixels": 500,
                        "items": [],
                    },
                },
                "physical_area_m2": None,
                "physical_area_hectares": None,
                "coordinates": None,
            },
            confidence=ConfidenceProvenance(),
            warnings=["fake runtime warning"],
            evidence={
                name: filename if Path(filename).is_absolute() else str(run_directory / filename)
                for name, filename in filenames.items()
            },
            timing=Timing(0.125, 0.025, 0.15),
        )


class WorkerApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_root = self.root / "inputs"
        self.output_root = self.root / "outputs"
        self.input_root.mkdir()
        self.before = self.input_root / "case-before.png"
        self.after = self.input_root / "case-after.png"
        Image.new("RGB", (256, 256), color=(10, 20, 30)).save(self.before)
        Image.new("RGB", (256, 256), color=(40, 50, 60)).save(self.after)
        self.config = WorkerConfig(
            input_root=self.input_root,
            output_root=self.output_root,
            checkpoint=self.root / "MCI_model.pth",
            device="cpu",
            busy_wait_seconds=0.01,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _payload(self, **updates: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": CONTRACT_VERSION,
            "request_id": str(uuid.uuid4()),
            "before_path": str(self.before.resolve()),
            "after_path": str(self.after.resolve()),
            "geo_metadata": None,
        }
        payload.update(updates)
        return payload

    def _ready_client(self, analyzer: FakeChangeAnalyzer | None = None) -> TestClient:
        state = WorkerState(self.config)
        state.mark_ready(
            analyzer or FakeChangeAnalyzer(),
            model_name="Change-Agent MCI",
            checkpoint_sha256="a" * 64,
            vocab_size=468,
        )
        return TestClient(create_app(state), raise_server_exceptions=False)

    def test_health_is_live_while_worker_is_starting(self) -> None:
        client = TestClient(create_app(WorkerState(self.config)))

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "satquery-mci-worker",
                "contract_version": "1.0",
            },
        )
        self.assertEqual(client.get("/ready").status_code, 503)

    def test_ready_reports_safe_failed_state(self) -> None:
        state = WorkerState(self.config)
        state.mark_failed("checkpoint initialization failed")
        client = TestClient(create_app(state))

        response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "MODEL_NOT_READY")
        self.assertNotIn(str(self.root), response.text)
        self.assertNotIn("traceback", response.text.lower())

    def test_success_sanitizes_result_and_echoes_request_id(self) -> None:
        client = self._ready_client()
        payload = self._payload()

        response = client.post("/v1/change-analysis", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["contract_version"], "1.0")
        self.assertEqual(body["request_id"], payload["request_id"])
        self.assertTrue(body["run_id"])
        self.assertEqual(body["caption"]["text"], "two buildings were constructed")
        self.assertEqual(body["statistics"]["changed_pixels"], 536)
        self.assertEqual(body["model"]["vocab_size"], 468)
        self.assertEqual(body["artifacts"]["overlay"], "overlay.png")
        self.assertNotIn(str(self.root), json.dumps(body))
        self.assertTrue((self.output_root / body["run_id"] / "overlay.png").is_file())
        self.assertEqual(
            ChangeAnalysisSuccessResponse.model_validate(body).model_dump(mode="json"),
            body,
        )

    def test_invalid_contract_and_request_id_return_safe_invalid_request(self) -> None:
        client = self._ready_client()

        response = client.post(
            "/v1/change-analysis",
            json=self._payload(contract_version="9.9", request_id="not-a-uuid"),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        self.assertNotIn("detail", response.json())

    def test_outside_root_and_missing_input_are_rejected(self) -> None:
        client = self._ready_client()
        outside = self.root / "outside.png"
        outside.write_bytes(b"outside")

        outside_response = client.post(
            "/v1/change-analysis", json=self._payload(before_path=str(outside.resolve()))
        )
        missing_response = client.post(
            "/v1/change-analysis",
            json=self._payload(before_path=str((self.input_root / "missing.png").resolve())),
        )

        self.assertEqual(outside_response.status_code, 422)
        self.assertEqual(outside_response.json()["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(missing_response.status_code, 422)
        self.assertEqual(missing_response.json()["error"]["code"], "INPUT_FILE_NOT_FOUND")
        self.assertNotIn(str(self.root), outside_response.text)

    def test_unsupported_image_is_rejected_before_runtime(self) -> None:
        client = self._ready_client()
        invalid = self.input_root / "not-an-image.png"
        invalid.write_bytes(b"not an image")

        response = client.post(
            "/v1/change-analysis", json=self._payload(before_path=str(invalid.resolve()))
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_IMAGE")

    def test_artifact_escape_is_rejected_without_path_leakage(self) -> None:
        client = self._ready_client(FakeChangeAnalyzer(outside_artifact=True))

        response = client.post("/v1/change-analysis", json=self._payload())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "ARTIFACT_WRITE_FAILED")
        self.assertNotIn(str(self.root), response.text)

    def test_runtime_failure_does_not_leak_internal_error(self) -> None:
        client = self._ready_client(FakeChangeAnalyzer(fail=True))

        response = client.post("/v1/change-analysis", json=self._payload())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INFERENCE_FAILED")
        self.assertNotIn("private", response.text)
        self.assertNotIn(str(self.root), response.text)

    def test_second_overlapping_request_is_busy(self) -> None:
        analyzer = FakeChangeAnalyzer(wait_for_release=True)
        client = self._ready_client(analyzer)

        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, "/v1/change-analysis", json=self._payload())
            self.assertTrue(analyzer.started.wait(timeout=1))
            second = client.post("/v1/change-analysis", json=self._payload())
            analyzer.release.set()
            first_response = first.result(timeout=2)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["error"], {
            "code": "WORKER_BUSY",
            "message": "The worker is busy; retry shortly.",
            "retryable": True,
        })


if __name__ == "__main__":
    unittest.main()
