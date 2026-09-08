"""Opt-in CUDA/checkpoint E2E through the real SatQuery HTTP boundaries."""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin

from satquery.contracts import ResultEnvelope


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_TOOL2_REAL_E2E") != "1",
    reason="Set RUN_TOOL2_REAL_E2E=1 for the real CUDA/checkpoint shared-app test",
)

EXPECTED_CHECKPOINT_SHA256 = "34c6926342c40fdd6d50b43d50257cb46cb6b61763448de9ee551828a64b3eb9"
EXPECTED_MASK_SHA256 = "b6e9c476be46ecfbdfe074c50c9604fd78d2c528e4fa410c3d99f3ef568953ce"
EXPECTED_CAPTION = "the vegetation has been removed and a road with villas built along appears"
EXPECTED_ANSWER = (
    "The vegetation has been removed and a road with villas built along appears. "
    "Changed pixels: 19,938 (30.42% of valid pixels). "
    "Road change: 11.26% of valid pixels; building change: 19.16% of valid pixels."
)
PUBLIC_ARTIFACTS = {
    "overlay": ("image/png", (256, 256)),
    "semantic_mask_rgb": ("image/png", (256, 256)),
    "semantic_mask": ("image/png", (256, 256)),
    "binary_mask": ("image/png", (256, 256)),
    "components": ("application/json", None),
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture(png_path: Path, tiff_path: Path) -> dict[str, Any]:
    source = np.asarray(Image.open(png_path).convert("RGB"), dtype=np.uint8)
    assert source.shape == (256, 256, 3)
    with rasterio.open(
        tiff_path,
        "w",
        driver="GTiff",
        width=256,
        height=256,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(10.0, 10.0, 0.001, 0.001),
    ) as target:
        target.write(np.moveaxis(source, -1, 0))
        for index, name in enumerate(("red", "green", "blue"), start=1):
            target.set_band_description(index, name)
        target.update_tags(SATQUERY_FIXTURE="synthetic-grid-no-real-geography")
    with rasterio.open(tiff_path) as decoded:
        restored = np.moveaxis(decoded.read(), 0, -1)
        assert decoded.crs is not None and not decoded.crs.is_projected
    np.testing.assert_array_equal(restored, source)
    return {
        "png_pixel_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "tiff_pixel_sha256": hashlib.sha256(restored.tobytes()).hexdigest(),
        "pixel_equal": True,
    }


def _stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=15)


def _wait_json(url: str, deadline_seconds: float) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    deadline = started + deadline_seconds
    last_error: Exception | None = None
    while time.perf_counter() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code == 200:
                return response.json(), time.perf_counter() - started
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
        time.sleep(0.25)
    raise AssertionError(f"Process did not become ready at {url}") from last_error


def _gpu_memory() -> dict[str, int] | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        used, free = (int(value.strip()) for value in result.stdout.strip().split(",")[:2])
        return {"used_mib": used, "free_mib": free}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _upload(client: httpx.Client, path: Path, date: str) -> dict[str, Any]:
    with path.open("rb") as handle:
        response = client.post(
            "/api/upload",
            data={"modality": "optical", "acquisition_date": date},
            files={"file": (path.name, handle, "image/tiff")},
        )
    assert response.status_code == 201, response.text
    payload = response.json()
    metadata = payload["metadata"]
    assert (metadata["width"], metadata["height"], metadata["band_count"]) == (256, 256, 3)
    assert metadata["dtypes"] == ["uint8", "uint8", "uint8"]
    return payload


def _query(client: httpx.Client, before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = client.post(
        "/api/query",
        json={"asset_ids": [before["asset_id"], after["asset_id"]], "question": "What changed?"},
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    result = ResultEnvelope.model_validate(response.json()).model_dump(mode="json")
    assert result["task"] == "change"
    assert result["tools"] == ["checker_v1", "router_v1", "change_mci_v1"]
    assert "change_stub_v0" not in result["tools"]
    assert result["receipt"]["rejected"] is False
    assert result["receipt"]["trace"][-1]["status"] == "ok"
    assert result["confidence"] == 0.0
    assert result["facts"]["confidence_status"] == "not_measured"
    assert result["facts"]["physical_area_m2"] is None
    assert result["facts"]["physical_area_hectares"] is None
    return result, elapsed


def _verify_artifacts(client: httpx.Client, result: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for key, (media_type, dimensions) in PUBLIC_ARTIFACTS.items():
        url = result["facts"]["artifacts"][key]
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"].split(";", 1)[0] == media_type
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content
        if dimensions is not None:
            image = Image.open(io.BytesIO(response.content))
            assert image.size == dimensions
        else:
            assert isinstance(response.json(), dict)
        report[key] = {
            "http": response.status_code,
            "content_type": media_type,
            "bytes": len(response.content),
            "dimensions": dimensions,
        }
    run_url = result["facts"]["artifacts"]["overlay"].rsplit("/", 1)[0]
    for private_name in ("result.json", "access.json"):
        private = client.get(f"{run_url}/{private_name}")
        assert private.status_code == 404
        report[private_name] = {"http": private.status_code}
    return report


def _assert_positive(result: dict[str, Any]) -> None:
    facts = result["facts"]
    assert facts["caption"]["text"] == EXPECTED_CAPTION
    assert facts["classes"]["unchanged_background"]["pixel_count"] == 45598
    assert facts["classes"]["road_change"]["pixel_count"] == 7382
    assert facts["classes"]["building_change"]["pixel_count"] == 12556
    assert facts["changed_pixels"] == 19938
    assert facts["unchanged_pixels"] + facts["changed_pixels"] == facts["valid_pixels"] == 65536
    assert facts["changed_percent"] == pytest.approx(30.4229736328125)
    assert result["answer_text"] == EXPECTED_ANSWER
    assert "confidence" not in result["answer_text"].lower()
    assert "components" not in result["answer_text"].lower()


def _assert_no_change(result: dict[str, Any]) -> None:
    facts = result["facts"]
    assert facts["caption"]["text"] == "the scene is the same as before"
    assert facts["classes"]["unchanged_background"]["pixel_count"] == 65536
    assert facts["classes"]["road_change"]["pixel_count"] == 0
    assert facts["classes"]["building_change"]["pixel_count"] == 0
    assert facts["changed_pixels"] == 0
    assert facts["changed_percent"] == 0
    assert result["answer_text"] == "The scene is the same as before. Changed pixels: 0 (0.00% of valid pixels)."


def test_real_cuda_checkpoint_through_shared_app_and_browser() -> None:
    root = Path(__file__).resolve().parents[2]
    checkpoint = root / "MCI_model.pth"
    dataset = root / "LEVIR-MCI-dataset" / "images" / "test"
    worker_python = root / ".venv-mci" / "Scripts" / "python.exe"
    main_python = root / ".venv" / "Scripts" / "python.exe"
    assert _sha256(checkpoint) == EXPECTED_CHECKPOINT_SHA256
    assert worker_python.is_file() and main_python.is_file()

    worker_process: subprocess.Popen[str] | None = None
    main_process: subprocess.Popen[str] | None = None
    with tempfile.TemporaryDirectory(prefix="tool2-e2e-", dir=root / "runtime") as temp_name:
        temp_root = Path(temp_name)
        upload_root = temp_root / "uploads"
        output_root = upload_root / "tool2-results"
        fixture_root = temp_root / "fixtures"
        fixture_root.mkdir(parents=True)
        positive_before = fixture_root / "test_000004_before.tif"
        positive_after = fixture_root / "test_000004_after.tif"
        negative_before = fixture_root / "test_000005_before.tif"
        negative_after = fixture_root / "test_000005_after.tif"
        fixture_report = {
            "test_000004_before": _fixture(dataset / "A" / "test_000004.png", positive_before),
            "test_000004_after": _fixture(dataset / "B" / "test_000004.png", positive_after),
            "test_000005_before": _fixture(dataset / "A" / "test_000005.png", negative_before),
            "test_000005_after": _fixture(dataset / "B" / "test_000005.png", negative_after),
        }

        worker_port = 8012
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            assert probe.connect_ex(("127.0.0.1", worker_port)) != 0, "Port 8012 is already in use"
        main_port = _free_port()
        worker_url = f"http://127.0.0.1:{worker_port}"
        main_url = f"http://127.0.0.1:{main_port}"
        worker_command = [
            str(worker_python), "-m", "experiments.tool2_mci.worker_cli",
            "--host", "127.0.0.1", "--port", str(worker_port),
            "--checkpoint", str(checkpoint), "--input-root", str(upload_root),
            "--output-root", str(output_root), "--device", "cuda:0",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            memory_before = _gpu_memory()
            worker_started = time.perf_counter()
            worker_process = subprocess.Popen(
                worker_command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=creationflags,
            )
            ready, _ = _wait_json(f"{worker_url}/ready", 120)
            startup_seconds = time.perf_counter() - worker_started
            assert ready == {
                "contract_version": "1.0", "status": "ready",
                "model": "Change-Agent MCI", "device": "cuda:0",
                "checkpoint_sha256": EXPECTED_CHECKPOINT_SHA256, "vocab_size": 468,
            }
            memory_ready = _gpu_memory()

            environment = os.environ.copy()
            environment.update({
                "SATQUERY_RUNTIME_DIR": str(upload_root),
                "SATQUERY_MCI_WORKER_URL": worker_url,
            })
            main_process = subprocess.Popen(
                [str(main_python), "apps/web/server.py", "--port", str(main_port)],
                cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=creationflags,
            )
            _wait_json(f"{main_url}/api/health", 30)

            with httpx.Client(base_url=main_url, timeout=90.0) as client:
                before = _upload(client, positive_before, "2024-01-01")
                after = _upload(client, positive_after, "2024-02-01")
                positive, positive_api_seconds = _query(client, before, after)
                _assert_positive(positive)
                positive_artifacts = _verify_artifacts(client, positive)
                raw_mask = client.get(positive["facts"]["artifacts"]["semantic_mask"]).content
                raw_mask_sha256 = hashlib.sha256(raw_mask).hexdigest()
                assert raw_mask_sha256 == EXPECTED_MASK_SHA256
                memory_positive = _gpu_memory()

                before_no_change = _upload(client, negative_before, "2024-03-01")
                after_no_change = _upload(client, negative_after, "2024-04-01")
                no_change, no_change_api_seconds = _query(client, before_no_change, after_no_change)
                _assert_no_change(no_change)
                no_change_artifacts = _verify_artifacts(client, no_change)
                memory_no_change = _gpu_memory()

            browser_environment = environment | {
                "SATQUERY_TEST_URL": main_url,
                "TOOL2_E2E_POSITIVE_BEFORE": str(positive_before),
                "TOOL2_E2E_POSITIVE_AFTER": str(positive_after),
                "TOOL2_E2E_NO_CHANGE_BEFORE": str(negative_before),
                "TOOL2_E2E_NO_CHANGE_AFTER": str(negative_after),
            }
            browser = subprocess.run(
                ["node", "tests/web/verify-tool2-real.cjs"], cwd=root,
                env=browser_environment, check=True, capture_output=True, text=True,
                timeout=180, creationflags=creationflags,
            )
            browser_line = next(
                line for line in browser.stdout.splitlines()
                if line.startswith("TOOL2_REAL_BROWSER_REPORT=")
            )
            browser_report = json.loads(browser_line.split("=", 1)[1])

            assert worker_process.poll() is None
            ready_after, _ = _wait_json(f"{worker_url}/ready", 5)
            assert ready_after == ready
            report = {
                "checkpoint_sha256": EXPECTED_CHECKPOINT_SHA256,
                "worker_pid": worker_process.pid,
                "worker_command": worker_command,
                "ready": ready,
                "worker_startup_seconds": startup_seconds,
                "fixtures": fixture_report,
                "positive": {
                    "asset_ids": [before["asset_id"], after["asset_id"]],
                    "caption": positive["facts"]["caption"]["text"],
                    "classes": {key: value["pixel_count"] for key, value in positive["facts"]["classes"].items()},
                    "changed_pixels": positive["facts"]["changed_pixels"],
                    "changed_percent": positive["facts"]["changed_percent"],
                    "answer_text": positive["answer_text"],
                    "model_inference_seconds": positive["facts"]["timing"]["inference_seconds"],
                    "api_query_seconds": positive_api_seconds,
                    "raw_mask_sha256": raw_mask_sha256,
                    "artifacts": positive_artifacts,
                },
                "no_change": {
                    "asset_ids": [before_no_change["asset_id"], after_no_change["asset_id"]],
                    "caption": no_change["facts"]["caption"]["text"],
                    "classes": {key: value["pixel_count"] for key, value in no_change["facts"]["classes"].items()},
                    "changed_pixels": no_change["facts"]["changed_pixels"],
                    "changed_percent": no_change["facts"]["changed_percent"],
                    "answer_text": no_change["answer_text"],
                    "model_inference_seconds": no_change["facts"]["timing"]["inference_seconds"],
                    "api_query_seconds": no_change_api_seconds,
                    "artifacts": no_change_artifacts,
                },
                "browser": browser_report,
                "gpu_memory": {
                    "before_worker": memory_before,
                    "worker_ready": memory_ready,
                    "after_positive": memory_positive,
                    "after_no_change": memory_no_change,
                },
                "model_reuse": {"same_worker_pid": True, "ready_state_unchanged": True, "api_analyses_before_browser": 2},
            }
            print("TOOL2_REAL_E2E_REPORT=" + json.dumps(report, sort_keys=True))
        finally:
            _stop(main_process)
            _stop(worker_process)
