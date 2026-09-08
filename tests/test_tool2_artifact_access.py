"""Public-access contract for completed Tool 2 evidence only."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.web import server as web_server
from tests.fake_mci_worker import successful_mci_client


RUN_ID = "c" * 32
PUBLIC_ARTIFACTS = {
    "overlay.png": "image/png",
    "semantic_mask_rgb.png": "image/png",
    "semantic_mask_raw.png": "image/png",
    "change_binary_mask.png": "image/png",
    "components.json": "application/json",
}


def _upload_pair(client: TestClient, geotiff_bytes) -> list[str]:
    asset_ids: list[str] = []
    for name, acquisition_date in (("before.tif", "2020-01-01"), ("after.tif", "2021-01-01")):
        response = client.post(
            "/upload",
            files={"file": (name, geotiff_bytes(width=256, height=256), "image/tiff")},
            data={"modality": "optical", "acquisition_date": acquisition_date},
        )
        assert response.status_code == 201, response.text
        asset_ids.append(response.json()["asset_id"])
    return asset_ids


def _write_completed_run(client: TestClient, asset_ids: list[str], *, run_id: str = RUN_ID) -> Path:
    root = client.app.state.store.root / "tool2-results" / run_id
    root.mkdir(parents=True, exist_ok=False)
    for filename in PUBLIC_ARTIFACTS:
        content = b'{"components":[]}' if filename == "components.json" else b"fake-tool2-png"
        (root / filename).write_bytes(content)
    result_path = root / "result.json"
    evidence = {
        "semantic_mask": str(root / "semantic_mask_raw.png"),
        "semantic_mask_rgb": str(root / "semantic_mask_rgb.png"),
        "binary_mask": str(root / "change_binary_mask.png"),
        "overlay": str(root / "overlay.png"),
        "components": str(root / "components.json"),
        "result": str(result_path),
    }
    result_path.write_text(json.dumps({"task": "change_analysis", "evidence": evidence}), encoding="utf-8")
    (root / "access.json").write_text(
        json.dumps({"asset_ids": asset_ids, "run_id": run_id, "tool": "change_mci_v1"}),
        encoding="utf-8",
    )
    return root


def test_completed_run_serves_only_the_five_public_artifacts(client, geotiff_bytes):
    asset_ids = _upload_pair(client, geotiff_bytes)
    root = _write_completed_run(client, asset_ids)

    for filename, media_type in PUBLIC_ARTIFACTS.items():
        response = client.get(f"/artifacts/tool2/{RUN_ID}/{filename}")

        assert response.status_code == 200
        assert response.headers["content-type"].split(";", 1)[0] == media_type
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert response.content == (root / filename).read_bytes()


@pytest.mark.parametrize(
    "filename",
    (
        "result.json",
        "access.json",
        "before.png",
        "after.png",
        "checkpoint.pth",
        "unexpected.png",
        "nested/overlay.png",
        "..%2Foverlay.png",
        "..\\overlay.png",
    ),
)
def test_private_or_unsafe_artifact_names_are_not_served(client, geotiff_bytes, filename):
    asset_ids = _upload_pair(client, geotiff_bytes)
    root = _write_completed_run(client, asset_ids)
    for private in ("access.json", "before.png", "after.png", "checkpoint.pth", "unexpected.png"):
        (root / private).write_text("private", encoding="utf-8")

    response = client.get(f"/artifacts/tool2/{RUN_ID}/{filename}")

    assert response.status_code == 404
    assert str(client.app.state.store.root) not in response.text
    assert "C:\\Users" not in response.text


@pytest.mark.parametrize(
    "run_id",
    ("", "C" * 32, "c" * 31, "c" * 33, "../" + RUN_ID, RUN_ID + ".", " c" * 16),
)
def test_invalid_or_missing_run_ids_are_not_served(client, geotiff_bytes, run_id):
    asset_ids = _upload_pair(client, geotiff_bytes)
    _write_completed_run(client, asset_ids)

    response = client.get(f"/artifacts/tool2/{run_id}/overlay.png")

    assert response.status_code == 404
    assert str(client.app.state.store.root) not in response.text


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_access",
        "malformed_access",
        "wrong_access_run",
        "wrong_access_tool",
        "noncanonical_asset_id",
        "duplicate_asset_ids",
        "missing_result",
        "malformed_result",
        "wrong_result_task",
        "not_advertised",
        "missing_artifact",
    ),
)
def test_malformed_or_incomplete_runs_are_not_served(client, geotiff_bytes, mutation):
    asset_ids = _upload_pair(client, geotiff_bytes)
    root = _write_completed_run(client, asset_ids)
    access = root / "access.json"
    result = root / "result.json"
    if mutation == "missing_access":
        access.unlink()
    elif mutation == "malformed_access":
        access.write_text("{invalid", encoding="utf-8")
    elif mutation == "wrong_access_run":
        access.write_text(json.dumps({"asset_ids": asset_ids, "run_id": "d" * 32, "tool": "change_mci_v1"}), encoding="utf-8")
    elif mutation == "wrong_access_tool":
        access.write_text(json.dumps({"asset_ids": asset_ids, "run_id": RUN_ID, "tool": "other_tool"}), encoding="utf-8")
    elif mutation == "noncanonical_asset_id":
        access.write_text(json.dumps({"asset_ids": [asset_ids[0].upper(), asset_ids[1]], "run_id": RUN_ID, "tool": "change_mci_v1"}), encoding="utf-8")
    elif mutation == "duplicate_asset_ids":
        access.write_text(json.dumps({"asset_ids": [asset_ids[0], asset_ids[0]], "run_id": RUN_ID, "tool": "change_mci_v1"}), encoding="utf-8")
    elif mutation == "missing_result":
        result.unlink()
    elif mutation == "malformed_result":
        result.write_text("{invalid", encoding="utf-8")
    elif mutation == "wrong_result_task":
        result.write_text(json.dumps({"task": "other", "evidence": {"result": str(result)}}), encoding="utf-8")
    elif mutation == "not_advertised":
        result.write_text(json.dumps({"task": "change_analysis", "evidence": {"result": str(result)}}), encoding="utf-8")
    elif mutation == "missing_artifact":
        (root / "overlay.png").unlink()

    response = client.get(f"/artifacts/tool2/{RUN_ID}/overlay.png")

    assert response.status_code == 404
    assert str(client.app.state.store.root) not in response.text


def test_expired_or_removed_source_blocks_existing_evidence(client, geotiff_bytes):
    asset_ids = _upload_pair(client, geotiff_bytes)
    root = _write_completed_run(client, asset_ids)
    client.app.state.store.discard(UUID(asset_ids[0]))

    response = client.get(f"/artifacts/tool2/{RUN_ID}/overlay.png")

    assert response.status_code == 404
    assert (root / "overlay.png").is_file()


def test_prefix_collision_directory_cannot_be_resolved_as_tool2_output(client, geotiff_bytes):
    asset_ids = _upload_pair(client, geotiff_bytes)
    run = _write_completed_run(client, asset_ids)
    outside = client.app.state.store.root / "tool2-results-evil" / RUN_ID
    outside.parent.mkdir()
    run.rename(outside)

    response = client.get(f"/artifacts/tool2/{RUN_ID}/overlay.png")

    assert response.status_code == 404
    assert str(client.app.state.store.root) not in response.text


def test_symlinked_run_directory_cannot_escape_tool2_output_root(client, geotiff_bytes):
    asset_ids = _upload_pair(client, geotiff_bytes)
    run = _write_completed_run(client, asset_ids)
    outside = client.app.state.store.root / "tool2-results-evil" / RUN_ID
    outside.parent.mkdir()
    run.rename(outside)
    try:
        run.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Windows symlink creation is unavailable: {error}")

    response = client.get(f"/artifacts/tool2/{RUN_ID}/overlay.png")

    assert response.status_code == 404
    assert str(client.app.state.store.root) not in response.text


def test_fake_worker_query_produces_fetchable_public_evidence(settings, geotiff_bytes):
    seen_requests: list[dict] = []
    worker_client = successful_mci_client(settings.runtime_dir / "tool2-results", seen_requests)
    try:
        with TestClient(create_app(settings, mci_client=worker_client)) as api:
            asset_ids = _upload_pair(api, geotiff_bytes)
            query = api.post(
                "/query",
                json={"asset_ids": asset_ids, "question": "What changed?"},
            )
            assert query.status_code == 200, query.text
            result = query.json()
            artifact_urls = [
                result["overlay"]["file"],
                *result["facts"]["artifacts"].values(),
            ]
            responses = [api.get(url) for url in artifact_urls]
    finally:
        worker_client.close()

    assert seen_requests
    assert {response.status_code for response in responses} == {200}
    assert {response.headers["content-type"].split(";", 1)[0] for response in responses} == {
        "image/png",
        "application/json",
    }
    assert {response.content for response in responses} == {b"fake-worker-artifact"}


def test_mounted_api_query_generates_and_serves_tool2_urls_under_api_prefix(
    settings, tmp_path, geotiff_bytes, monkeypatch
):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>test</html>", encoding="utf-8")
    worker_client = successful_mci_client(settings.runtime_dir / "tool2-results", [])
    monkeypatch.setattr(
        web_server,
        "create_app",
        lambda active_settings: create_app(active_settings, mci_client=worker_client),
    )
    try:
        with TestClient(web_server.create_web_app(settings, static_dir=static)) as mounted:
            asset_ids = []
            for name, acquisition_date in (("before.tif", "2020-01-01"), ("after.tif", "2021-01-01")):
                response = mounted.post(
                    "/api/upload",
                    files={"file": (name, geotiff_bytes(width=256, height=256), "image/tiff")},
                    data={"modality": "optical", "acquisition_date": acquisition_date},
                )
                assert response.status_code == 201, response.text
                asset_ids.append(response.json()["asset_id"])
            query = mounted.post(
                "/api/query",
                json={"asset_ids": asset_ids, "question": "What changed?"},
            )
            assert query.status_code == 200, query.text
            artifact_url = query.json()["overlay"]["file"]
            response = mounted.get(artifact_url)
    finally:
        worker_client.close()

    assert artifact_url == f"/api/artifacts/tool2/{'b' * 32}/overlay.png"
    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "image/png"
