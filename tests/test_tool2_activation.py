import json

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.main import Settings, create_app
from satquery.registry import TOOL_REGISTRY, is_stub_tool
from satquery.tools.change_mci import change_mci_v1
from satquery.tools.mci_worker_client import MCIWorkerClient
from tests.fake_mci_worker import successful_mci_client


def _failing_worker(mode, seen_requests):
    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if mode == "WORKER_UNAVAILABLE":
            raise httpx.ConnectError(r"C:\Users\Aryaveer\secret-worker-path")
        if mode == "WORKER_TIMEOUT":
            raise httpx.ReadTimeout("private timeout details")
        if mode == "INVALID_WORKER_RESPONSE":
            return httpx.Response(200, content=b"private invalid response body")
        status = 429 if mode == "WORKER_BUSY" else 503
        return httpx.Response(
            status,
            json={
                "contract_version": "1.0",
                "error": {
                    "code": mode,
                    "message": "A safe worker message.",
                    "retryable": mode == "WORKER_BUSY",
                },
            },
        )

    return MCIWorkerClient(transport=httpx.MockTransport(handler))


def _upload_change_pair(client, geotiff_bytes, *, width=256):
    asset_ids = []
    for name, date in (("before.tif", "2020-01-01"), ("after.tif", "2021-01-01")):
        response = client.post(
            "/upload",
            files={
                "file": (
                    name,
                    geotiff_bytes(width=width, height=256),
                    "image/tiff",
                )
            },
            data={"modality": "optical", "acquisition_date": date},
        )
        assert response.status_code == 201
        asset_ids.append(response.json()["asset_id"])
    return asset_ids


def test_registry_contains_real_change_specialist_and_keeps_explicit_stub():
    assert TOOL_REGISTRY["change_mci_v1"] is change_mci_v1
    assert "change_stub_v0" in TOOL_REGISTRY
    assert "single_image_stub_v0" in TOOL_REGISTRY
    assert "optical_sar_v1" in TOOL_REGISTRY
    assert is_stub_tool("change_stub_v0")
    assert is_stub_tool("single_image_stub_v0")
    assert not is_stub_tool("change_mci_v1")
    assert not is_stub_tool("optical_sar_v1")


def test_change_query_executes_registered_adapter_through_fake_http_worker(
    settings, geotiff_bytes
):
    seen_requests = []
    output_root = settings.runtime_dir / "tool2-results"
    worker_client = successful_mci_client(output_root, seen_requests)

    with TestClient(create_app(settings, mci_client=worker_client)) as client:
        uploads = _upload_change_pair(client, geotiff_bytes)

        response = client.post(
            "/query",
            json={
                "asset_ids": list(reversed(uploads)),
                "question": "What changed between the two dates?",
            },
        )
        artifact_response = client.get(response.json()["overlay"]["file"])

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["task"] == "change"
    assert result["tools"][-1] == "change_mci_v1"
    assert result["receipt"]["trace"][-1]["status"] == "ok"
    assert result["receipt"]["trace"][-1]["details"]["overlay_type"] == "change_mask"
    assert result["facts"]["caption"]["text"] == "a road was constructed"
    assert result["facts"]["confidence_status"] == "not_measured"
    assert result["confidence"] == 0.0
    assert result["overlay"] == {
        "type": "change_mask",
        "file": "/artifacts/tool2/" + "b" * 32 + "/overlay.png",
    }
    assert artifact_response.status_code == 200
    assert artifact_response.headers["content-type"].split(";", 1)[0] == "image/png"
    assert "question" not in seen_requests[0]
    assert seen_requests[0]["before_path"].endswith(uploads[0] + "\\source.tif")
    assert seen_requests[0]["after_path"].endswith(uploads[1] + "\\source.tif")
    assert str(settings.runtime_dir) not in response.text
    access = json.loads((output_root / ("b" * 32) / "access.json").read_text())
    assert access["asset_ids"] == uploads


def test_incompatible_change_input_becomes_rejected_result_without_worker_call(
    settings, geotiff_bytes
):
    seen_requests = []
    worker_client = successful_mci_client(
        settings.runtime_dir / "tool2-results", seen_requests
    )
    with TestClient(create_app(settings, mci_client=worker_client)) as client:
        asset_ids = _upload_change_pair(client, geotiff_bytes, width=255)
        response = client.post(
            "/query",
            json={"asset_ids": asset_ids, "question": "What changed?"},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["task"] == "reject"
    assert result["parameters"]["rejection_code"] == "UNSUPPORTED_IMAGE"
    assert result["receipt"]["rejected"] is True
    assert result["receipt"]["trace"][-1]["status"] == "rejected"
    assert "256x256" in result["receipt"]["reason"]
    assert str(settings.runtime_dir) not in response.text
    assert seen_requests == []


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        ("WORKER_UNAVAILABLE", 503),
        ("WORKER_TIMEOUT", 504),
        ("WORKER_BUSY", 429),
        ("MODEL_NOT_READY", 503),
        ("INVALID_WORKER_RESPONSE", 502),
    ],
)
def test_worker_infrastructure_failures_remain_safe_http_errors(
    settings, geotiff_bytes, mode, expected_status
):
    seen_requests = []
    worker_client = _failing_worker(mode, seen_requests)
    with TestClient(create_app(settings, mci_client=worker_client)) as client:
        asset_ids = _upload_change_pair(client, geotiff_bytes)
        response = client.post(
            "/query",
            json={"asset_ids": asset_ids, "question": "What changed?"},
        )

    assert response.status_code == expected_status
    result = response.json()
    assert result["error"]["code"] == mode
    assert "receipt" not in result
    assert len(seen_requests) == 1
    assert "Aryaveer" not in response.text
    assert "secret-worker-path" not in response.text
    assert "private" not in response.text


def test_worker_unavailable_never_falls_back_to_change_stub(
    settings, geotiff_bytes, monkeypatch
):
    def forbidden_stub(*_args, **_kwargs):
        raise AssertionError("change stub fallback executed")

    monkeypatch.setitem(TOOL_REGISTRY, "change_stub_v0", forbidden_stub)
    seen_requests = []
    with TestClient(
        create_app(
            settings,
            mci_client=_failing_worker("WORKER_UNAVAILABLE", seen_requests),
        )
    ) as client:
        asset_ids = _upload_change_pair(client, geotiff_bytes)
        response = client.post(
            "/query",
            json={"asset_ids": asset_ids, "question": "What changed?"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "WORKER_UNAVAILABLE"
    assert len(seen_requests) == 1


def test_settings_read_mci_worker_url_and_timeouts_from_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SATQUERY_RUNTIME_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SATQUERY_MCI_WORKER_URL", "http://127.0.0.1:9123")
    monkeypatch.setenv("SATQUERY_MCI_CONNECT_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("SATQUERY_MCI_ANALYSIS_TIMEOUT_SECONDS", "21.0")

    settings = Settings.from_environment()

    assert settings.mci_worker_url == "http://127.0.0.1:9123"
    assert settings.mci_connect_timeout_seconds == 2.5
    assert settings.mci_analysis_timeout_seconds == 21.0


def test_app_owns_one_configured_client_but_does_not_close_injected_client(
    settings
):
    configured = Settings(
        runtime_dir=settings.runtime_dir,
        max_upload_bytes=settings.max_upload_bytes,
        retention_hours=settings.retention_hours,
        mci_worker_url="http://127.0.0.1:9123",
        mci_connect_timeout_seconds=2.5,
        mci_analysis_timeout_seconds=21.0,
    )
    app = create_app(configured)
    owned = app.state.mci_client
    assert owned.base_url == "http://127.0.0.1:9123"
    assert owned.connect_timeout_seconds == 2.5
    assert owned.analysis_timeout_seconds == 21.0
    with TestClient(app):
        assert app.state.mci_client is owned
        assert not owned._client.is_closed
    assert owned._client.is_closed

    injected = MCIWorkerClient(transport=httpx.MockTransport(lambda _: None))
    injected_app = create_app(configured, mci_client=injected)
    with TestClient(injected_app):
        assert injected_app.state.mci_client is injected
    assert not injected._client.is_closed
    injected.close()
