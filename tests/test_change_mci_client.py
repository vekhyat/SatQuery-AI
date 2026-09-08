"""Torch-free HTTP client tests for the local MCI worker contract."""

from __future__ import annotations

import json
import unittest
import uuid

import httpx

from satquery.tools.change_mci_protocol import ChangeAnalysisRequest
from satquery.tools.mci_worker_client import MCIWorkerClient, MCIWorkerClientError


def success_payload(request_id: str) -> dict:
    return {
        "contract_version": "1.0",
        "request_id": request_id,
        "run_id": "a" * 32,
        "caption": {
            "text": "a road was constructed",
            "source": "Change-Agent MCI decoder",
            "question_conditioned": False,
        },
        "statistics": {
            "total_pixels": 65536,
            "valid_pixels": 65536,
            "unchanged_pixels": 65000,
            "changed_pixels": 536,
            "changed_fraction": 0.0081787109375,
            "changed_percent": 0.81787109375,
            "per_class": {
                "unchanged_background": {"class_id": 0, "label": "unchanged/background", "pixel_count": 65000, "percent_of_valid_pixels": 99.18},
                "road_change": {"class_id": 1, "label": "road change", "pixel_count": 36, "percent_of_valid_pixels": 0.05, "percent_of_changed_pixels": 6.71},
                "building_change": {"class_id": 2, "label": "building change", "pixel_count": 500, "percent_of_valid_pixels": 0.76, "percent_of_changed_pixels": 93.29},
            },
        },
        "components": {
            "minimum_component_pixels": 6,
            "connectivity": 8,
            "all_changed": {"raw_component_count": 1, "filtered_component_count": 1, "filtered_pixel_count": 536, "largest_component_pixels": 536, "top_components": []},
            "road_change": {"raw_component_count": 1, "filtered_component_count": 1, "filtered_pixel_count": 36, "largest_component_pixels": 36, "top_components": []},
            "building_change": {"raw_component_count": 1, "filtered_component_count": 1, "filtered_pixel_count": 500, "largest_component_pixels": 500, "top_components": []},
        },
        "geospatial": {"physical_area_m2": None, "physical_area_hectares": None, "coordinates": None},
        "confidence": {"status": "not_measured", "source": "model_does_not_expose_calibrated_confidence", "note": "No calibrated confidence is available."},
        "artifacts": {"semantic_mask": "semantic_mask_raw.png", "semantic_mask_rgb": "semantic_mask_rgb.png", "binary_mask": "change_binary_mask.png", "overlay": "overlay.png", "components": "components.json"},
        "timing": {"inference_seconds": 1.0, "postprocessing_seconds": 0.1, "total_seconds": 1.1},
        "model": {"name": "Change-Agent MCI", "checkpoint_sha256": "a" * 64, "device": "cuda:0", "vocab_size": 468},
        "warnings": [],
    }


class MCIWorkerClientTest(unittest.TestCase):
    def _request(self) -> ChangeAnalysisRequest:
        return ChangeAnalysisRequest(
            contract_version="1.0",
            request_id=uuid.uuid4(),
            before_path="C:/trusted/before.tif",
            after_path="C:/trusted/after.tif",
        )

    def test_analyze_validates_response_and_preserves_request_id(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=success_payload(json.loads(request.content)["request_id"]))

        request = self._request()
        client = MCIWorkerClient(transport=httpx.MockTransport(handler))

        response = client.analyze(request)

        self.assertEqual(response.request_id, request.request_id)
        self.assertEqual(seen[0].url.path, "/v1/change-analysis")
        self.assertEqual(json.loads(seen[0].content)["contract_version"], "1.0")

    def test_safe_worker_errors_and_transport_failures_do_not_leak_details(self) -> None:
        def busy(_: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"contract_version": "1.0", "error": {"code": "WORKER_BUSY", "message": "The worker is busy; retry shortly.", "retryable": True}})

        def unavailable(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(r"C:\Users\Aryaveer\secret-test-value")

        def not_ready(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"contract_version": "1.0", "error": {"code": "MODEL_NOT_READY", "message": "The MCI model is not ready.", "retryable": False}})

        for transport, expected in ((busy, "WORKER_BUSY"), (not_ready, "MODEL_NOT_READY"), (unavailable, "WORKER_UNAVAILABLE")):
            with self.subTest(expected=expected):
                with self.assertRaises(MCIWorkerClientError) as caught:
                    MCIWorkerClient(transport=httpx.MockTransport(transport)).analyze(self._request())
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn("Aryaveer", str(caught.exception))
                self.assertNotIn("secret-test-value", str(caught.exception))

    def test_timeout_malformed_mismatched_and_oversized_responses_are_safe(self) -> None:
        request = self._request()
        cases = [
            (lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("private timeout")), "WORKER_TIMEOUT", {}),
            (lambda _: httpx.Response(200, content=b"not json"), "INVALID_WORKER_RESPONSE", {}),
            (lambda _: httpx.Response(200, json={**success_payload(str(request.request_id)), "contract_version": "9.9"}), "INVALID_WORKER_RESPONSE", {}),
            (lambda _: httpx.Response(200, json=success_payload(str(uuid.uuid4()))), "INVALID_WORKER_RESPONSE", {}),
            (lambda _: httpx.Response(200, content=b"x" * 64), "INVALID_WORKER_RESPONSE", {"maximum_response_bytes": 16}),
        ]
        for handler, expected, options in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(MCIWorkerClientError) as caught:
                    MCIWorkerClient(transport=httpx.MockTransport(handler), **options).analyze(request)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn("private", str(caught.exception))

    def test_post_is_not_retried_after_transport_failure(self) -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("timeout")

        with self.assertRaises(MCIWorkerClientError):
            MCIWorkerClient(transport=httpx.MockTransport(handler)).analyze(self._request())
        self.assertEqual(calls, 1)
