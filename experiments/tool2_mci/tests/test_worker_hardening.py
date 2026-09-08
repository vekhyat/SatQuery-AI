"""Adversarial tests for the Phase 3B2 local worker boundary."""

from __future__ import annotations

import copy
import os
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from experiments.tool2_mci.tests.test_worker_api import FakeChangeAnalyzer
from experiments.tool2_mci.worker_api import WorkerConfig, WorkerState, create_app
from satquery.tools.change_mci_protocol import CONTRACT_VERSION


class FailOnceAnalyzer(FakeChangeAnalyzer):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def analyze(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(
                r"C:\Users\Aryaveer\MCI_model.pth CUDA kernel traceback secret-test-value"
            )
        return super().analyze(*args, **kwargs)


class ManyComponentsAnalyzer(FakeChangeAnalyzer):
    def analyze(self, *args, **kwargs):
        result = super().analyze(*args, **kwargs)
        components = copy.deepcopy(result.facts["components"])
        item = {
            "component_id": 1,
            "class": "building_change",
            "class_id": 2,
            "pixel_area": 7,
            "bounding_box_pixels": {"x_min": 0, "y_min": 0, "x_max_exclusive": 1, "y_max_exclusive": 1},
            "centroid_pixels": {"x": 0.0, "y": 0.0},
            "percent_of_total_changed_pixels": 1.0,
        }
        components["building_change"]["items"] = [
            {**item, "component_id": index} for index in range(1, 31)
        ]
        return replace(result, facts={**result.facts, "components": components})


class WorkerHardeningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_root = self.root / "uploads"
        self.output_root = self.root / "worker-output"
        self.input_root.mkdir()
        self.before = self.input_root / "before.tif"
        self.after = self.input_root / "after.tif"
        self._write_rgb_tiff(self.before)
        self._write_rgb_tiff(self.after, color=(50, 60, 70))
        self.config = WorkerConfig(
            input_root=self.input_root,
            output_root=self.output_root,
            checkpoint=self.root / "MCI_model.pth",
            device="cpu",
            busy_wait_seconds=0.03,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _write_rgb_tiff(path: Path, size: tuple[int, int] = (256, 256), color=(10, 20, 30)) -> None:
        Image.new("RGB", size, color=color).save(path, format="TIFF")

    def _payload(self, **updates: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": CONTRACT_VERSION,
            "request_id": str(uuid.uuid4()),
            "before_path": str(self.before.resolve()),
            "after_path": str(self.after.resolve()),
        }
        payload.update(updates)
        return payload

    def _client(self, analyzer=None) -> TestClient:
        state = WorkerState(self.config)
        state.mark_ready(
            analyzer or FakeChangeAnalyzer(),
            model_name="Change-Agent MCI",
            checkpoint_sha256="a" * 64,
            vocab_size=468,
        )
        return TestClient(create_app(state), raise_server_exceptions=False)

    def test_accepts_only_uint8_rgb_256_tiff_pair(self) -> None:
        client = self._client()

        response = client.post("/v1/change-analysis", json=self._payload())

        self.assertEqual(response.status_code, 200)

    def test_rejects_png_and_invalid_tiff_shapes_channels_and_content(self) -> None:
        client = self._client()
        invalids: list[Path] = []
        png = self.input_root / "png.png"
        Image.new("RGB", (256, 256)).save(png)
        invalids.append(png)
        wrong_size = self.input_root / "wrong-size.tif"
        self._write_rgb_tiff(wrong_size, size=(255, 256))
        invalids.append(wrong_size)
        grayscale = self.input_root / "gray.tif"
        Image.new("L", (256, 256)).save(grayscale, format="TIFF")
        invalids.append(grayscale)
        rgba = self.input_root / "rgba.tif"
        Image.new("RGBA", (256, 256)).save(rgba, format="TIFF")
        invalids.append(rgba)
        uint16 = self.input_root / "uint16.tif"
        Image.new("I;16", (256, 256)).save(uint16, format="TIFF")
        invalids.append(uint16)
        corrupt = self.input_root / "corrupt.tif"
        corrupt.write_bytes(b"not a tiff")
        invalids.append(corrupt)

        for invalid in invalids:
            with self.subTest(invalid=invalid.name):
                response = client.post(
                    "/v1/change-analysis",
                    json=self._payload(before_path=str(invalid.resolve())),
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_IMAGE")

    def test_containment_rejects_prefix_collision_traversal_and_directories(self) -> None:
        client = self._client()
        prefix_collision = self.root / "uploads-evil" / "outside.tif"
        prefix_collision.parent.mkdir()
        self._write_rgb_tiff(prefix_collision)
        nested = self.input_root / "nested"
        nested.mkdir()
        directory = self.input_root / "directory.tif"
        directory.mkdir()
        cases = [
            str(prefix_collision.resolve()),
            str((nested / ".." / ".." / "uploads-evil" / "outside.tif")),
            str(directory.resolve()),
        ]

        for value in cases:
            with self.subTest(value=value):
                response = client.post("/v1/change-analysis", json=self._payload(before_path=value))
                self.assertEqual(response.status_code, 422)
                self.assertIn(response.json()["error"]["code"], {"INVALID_REQUEST", "INPUT_FILE_NOT_FOUND"})

    def test_symlink_escape_is_rejected_or_skipped_when_windows_disallows_it(self) -> None:
        escape_root = self.root / "outside"
        escape_root.mkdir()
        escaped = escape_root / "escaped.tif"
        self._write_rgb_tiff(escaped)
        link = self.input_root / "escape-link.tif"
        try:
            os.symlink(escaped, link)
        except OSError as error:
            self.skipTest(f"Windows symlink creation unavailable: {error.winerror}")

        response = self._client().post(
            "/v1/change-analysis", json=self._payload(before_path=str(link.resolve()))
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_run_ids_are_worker_generated_distinct_and_public_artifacts_are_allowlisted(self) -> None:
        client = self._client()

        first = client.post("/v1/change-analysis", json=self._payload()).json()
        second = client.post("/v1/change-analysis", json=self._payload()).json()

        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertRegex(first["run_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(
            set(first["artifacts"]),
            {"semantic_mask", "semantic_mask_rgb", "binary_mask", "overlay", "components"},
        )
        self.assertNotIn("result", first["artifacts"])
        self.assertNotIn("before", first["artifacts"])
        self.assertTrue((self.output_root / first["run_id"] / "result.json").is_file())

    def test_component_response_is_bounded_to_ten_items(self) -> None:
        body = self._client(ManyComponentsAnalyzer()).post(
            "/v1/change-analysis", json=self._payload()
        ).json()

        group = body["components"]["building_change"]
        self.assertEqual(group["raw_component_count"], 1)
        self.assertEqual(group["largest_component_pixels"], 500)
        self.assertEqual(len(group["top_components"]), 10)

    def test_failure_releases_slot_and_does_not_leak_sensitive_text(self) -> None:
        client = self._client(FailOnceAnalyzer())

        failed = client.post("/v1/change-analysis", json=self._payload())
        recovered = client.post("/v1/change-analysis", json=self._payload())

        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["error"]["code"], "INFERENCE_FAILED")
        for sensitive in ("Aryaveer", "MCI_model.pth", "CUDA", "traceback", "secret-test-value"):
            self.assertNotIn(sensitive, failed.text)
        self.assertEqual(recovered.status_code, 200)

    def test_busy_request_returns_then_worker_recovers_for_third_request(self) -> None:
        analyzer = FakeChangeAnalyzer(wait_for_release=True)
        client = self._client(analyzer)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, "/v1/change-analysis", json=self._payload())
            self.assertTrue(analyzer.started.wait(timeout=1))
            started = time.perf_counter()
            second = client.post("/v1/change-analysis", json=self._payload())
            elapsed = time.perf_counter() - started
            analyzer.release.set()
            self.assertEqual(first.result(timeout=2).status_code, 200)

        third = client.post("/v1/change-analysis", json=self._payload())
        self.assertEqual(second.status_code, 429)
        self.assertTrue(second.json()["error"]["retryable"])
        self.assertGreaterEqual(elapsed, self.config.busy_wait_seconds * 0.5)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(third.status_code, 200)
