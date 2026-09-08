"""Real loopback-process checks for the local worker boundary."""

from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

from satquery.tools.change_mci_protocol import ChangeAnalysisSuccessResponse


class WorkerProcessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_root = self.root / "inputs"
        self.output_root = self.root / "outputs"
        self.input_root.mkdir()
        self.before = self.input_root / "before.tif"
        self.after = self.input_root / "after.tif"
        Image.new("RGB", (256, 256), color=(10, 20, 30)).save(self.before, format="TIFF")
        Image.new("RGB", (256, 256), color=(40, 50, 60)).save(self.after, format="TIFF")
        self.processes: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.temporary_directory.cleanup()

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    @staticmethod
    def _request(url: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method="POST" if data else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=1) as response:
                return response.status, dict(response.headers.items()), json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers.items()), json.loads(error.read())

    def _start(self, state: str) -> str:
        port = self._free_loopback_port()
        process = subprocess.Popen(
            [
                str(Path(".venv-mci/Scripts/python.exe").resolve()),
                "-m",
                "experiments.tool2_mci.tests.fake_worker_server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--input-root",
                str(self.input_root),
                "--output-root",
                str(self.output_root),
                "--state",
                state,
            ],
            cwd=Path.cwd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.processes.append(process)
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if self._request(f"{url}/health")[0] == 200:
                    return url
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        self.fail("fake worker did not become reachable on loopback")

    def _payload(self) -> dict[str, str]:
        return {
            "contract_version": "1.0",
            "request_id": str(uuid.uuid4()),
            "before_path": str(self.before.resolve()),
            "after_path": str(self.after.resolve()),
        }

    def test_ready_fake_worker_serves_loopback_http_without_cors(self) -> None:
        url = self._start("ready")

        health_status, headers, health = self._request(f"{url}/health")
        ready_status, _, ready = self._request(f"{url}/ready")
        analysis_status, _, analysis = self._request(
            f"{url}/v1/change-analysis", self._payload()
        )

        self.assertEqual(health_status, 200)
        self.assertEqual(health["service"], "satquery-mci-worker")
        self.assertNotIn("access-control-allow-origin", {key.lower() for key in headers})
        self.assertEqual(ready_status, 200)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(analysis_status, 200)
        ChangeAnalysisSuccessResponse.model_validate(analysis)

    def test_starting_and_failed_processes_remain_live_but_not_ready(self) -> None:
        for state in ("starting", "failed"):
            with self.subTest(state=state):
                url = self._start(state)
                self.assertEqual(self._request(f"{url}/health")[0], 200)
                ready_status, _, ready = self._request(f"{url}/ready")
                analysis_status, _, analysis = self._request(
                    f"{url}/v1/change-analysis", self._payload()
                )
                self.assertEqual(ready_status, 503)
                self.assertEqual(ready["error"]["code"], "MODEL_NOT_READY")
                self.assertEqual(analysis_status, 503)
                self.assertEqual(analysis["error"]["code"], "MODEL_NOT_READY")


if __name__ == "__main__":
    unittest.main()
