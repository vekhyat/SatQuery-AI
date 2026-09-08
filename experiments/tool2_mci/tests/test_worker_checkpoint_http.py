"""Opt-in real HTTP regression against the frozen official MCI checkpoint."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from satquery.tools.change_mci_protocol import ChangeAnalysisSuccessResponse


@unittest.skipUnless(
    os.environ.get("RUN_MCI_WORKER_CHECKPOINT_TEST") == "1",
    "Set RUN_MCI_WORKER_CHECKPOINT_TEST=1 for the expensive worker HTTP regression",
)
class WorkerCheckpointHttpRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temporary_directory.name) / "worker-output"
        self.port = self._free_loopback_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen | None = None

    def tearDown(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.temporary_directory.cleanup()

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def _request(self, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method="POST" if data else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def _start_worker(self) -> None:
        image_root = self.root / "LEVIR-MCI-dataset" / "images" / "test"
        self.process = subprocess.Popen(
            [
                str((self.root / ".venv-mci" / "Scripts" / "python.exe").resolve()),
                "-m",
                "experiments.tool2_mci.tests.checkpoint_worker_server",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--checkpoint",
                str(self.root / "MCI_model.pth"),
                "--input-root",
                str(image_root),
                "--output-root",
                str(self.output_root),
                "--device",
                "cuda:0",
            ],
            cwd=self.root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if self._request("/health")[0] == 200:
                    return
            except (OSError, urllib.error.URLError):
                time.sleep(0.25)
        self.fail("checkpoint worker did not become reachable")

    def test_test_000004_matches_frozen_result_through_http(self) -> None:
        self._start_worker()
        ready_status, ready = self._request("/ready")
        input_root = self.root / "LEVIR-MCI-dataset" / "images" / "test"
        status, body = self._request(
            "/v1/change-analysis",
            {
                "contract_version": "1.0",
                "request_id": str(uuid.uuid4()),
                "before_path": str(input_root / "A" / "test_000004.png"),
                "after_path": str(input_root / "B" / "test_000004.png"),
            },
        )

        self.assertEqual(ready_status, 200)
        self.assertEqual(ready["model"], "Change-Agent MCI")
        self.assertEqual(ready["device"], "cuda:0")
        self.assertEqual(ready["vocab_size"], 468)
        self.assertEqual(status, 200)
        response = ChangeAnalysisSuccessResponse.model_validate(body)
        self.assertEqual(
            response.caption.text,
            "the vegetation has been removed and a road with villas built along appears",
        )
        self.assertEqual(response.statistics.per_class["unchanged_background"].pixel_count, 45598)
        self.assertEqual(response.statistics.per_class["road_change"].pixel_count, 7382)
        self.assertEqual(response.statistics.per_class["building_change"].pixel_count, 12556)
        self.assertEqual(response.statistics.changed_pixels, 19938)
        self.assertTrue((self.output_root / response.run_id / "components.json").is_file())
        self.assertNotIn(str(self.root), json.dumps(body))


if __name__ == "__main__":
    unittest.main()
