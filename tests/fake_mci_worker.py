"""Torch-free HTTP worker fixture for main-process integration tests."""

import json
from pathlib import Path

import httpx

from satquery.tools.mci_worker_client import MCIWorkerClient
from tests.test_change_mci_client import success_payload


def successful_mci_client(
    output_root: Path,
    seen_requests: list[dict],
    *,
    run_id: str = "b" * 32,
) -> MCIWorkerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_requests.append(payload)
        run_directory = output_root / run_id
        run_directory.mkdir(parents=True, exist_ok=True)
        for filename in (
            "semantic_mask_raw.png",
            "semantic_mask_rgb.png",
            "change_binary_mask.png",
            "overlay.png",
            "components.json",
        ):
            (run_directory / filename).write_bytes(b"fake-worker-artifact")
        result_path = run_directory / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "task": "change_analysis",
                    "evidence": {
                        "semantic_mask": str(run_directory / "semantic_mask_raw.png"),
                        "semantic_mask_rgb": str(run_directory / "semantic_mask_rgb.png"),
                        "binary_mask": str(run_directory / "change_binary_mask.png"),
                        "overlay": str(run_directory / "overlay.png"),
                        "components": str(run_directory / "components.json"),
                        "result": str(result_path),
                    },
                }
            ),
            encoding="utf-8",
        )
        response = success_payload(payload["request_id"])
        response["run_id"] = run_id
        response["warnings"] = [
            "Caption is model-generated and is not question-conditioned."
        ]
        return httpx.Response(200, json=response)

    return MCIWorkerClient(transport=httpx.MockTransport(handler))
