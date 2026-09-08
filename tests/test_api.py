from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from apps.api.main import Settings, create_app

RESULT_KEYS = {
    "task",
    "tools",
    "parameters",
    "facts",
    "answer_text",
    "confidence",
    "warnings",
    "overlay",
    "receipt",
}


def upload(
    client: TestClient,
    content: bytes,
    *,
    name: str = "scene.tif",
    modality: str = "auto",
    acquisition_date: str | None = None,
):
    data = {"modality": modality}
    if acquisition_date is not None:
        data["acquisition_date"] = acquisition_date
    return client.post(
        "/upload",
        files={"file": (name, content, "image/tiff")},
        data=data,
    )


def query(client: TestClient, asset_ids: list[str], question: str):
    return client.post(
        "/query",
        json={"asset_ids": asset_ids, "question": question},
    )


def test_health_has_versions_without_paths(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "checker": "checker_v1",
        "router": "router_v1",
    }
    assert "runtime" not in response.text.lower()


def test_upload_inspects_and_persists_a_valid_geotiff(
    geotiff_bytes: Callable[..., bytes], settings: Settings
) -> None:
    content = geotiff_bytes(
        tags={"SATELLITE": "Sentinel-2", "ACQUISITION_DATE": "2026-08-01"},
        descriptions=["red", "green", "blue"],
    )
    with TestClient(create_app(settings)) as first_client:
        response = upload(first_client, content, name="../unsafe-name.tif")
        assert response.status_code == 201
        body = response.json()
        assert body["original_name"] == "unsafe-name.tif"
        assert body["metadata"]["driver"] == "GTiff"
        assert body["metadata"]["modality"] == "optical"
        assert body["metadata"]["acquisition_date"] == "2026-08-01"
        assert body["sha256"]
        assert "runtime" not in response.text.lower()

    with TestClient(create_app(settings)) as restarted_client:
        result = query(restarted_client, [body["asset_id"]], "Describe this scene")
        assert result.status_code == 200
        assert result.json()["task"] == "single_image"


def test_user_hints_override_detected_metadata_with_provenance(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    response = upload(
        client,
        geotiff_bytes(tags={"MODALITY": "SAR", "DATE_ACQUIRED": "2020-01-01"}, bands=2),
        modality="optical",
        acquisition_date="2021-02-03",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["metadata"]["modality"] == "optical"
    assert body["metadata"]["acquisition_date"] == "2021-02-03"
    assert body["metadata"]["provenance"]["modality"]["source"] == "user"
    assert body["metadata"]["provenance"]["modality"]["detected_value"] == "sar"
    assert len(body["warnings"]) == 2


def test_single_image_route_is_an_honest_stub(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    uploaded = upload(client, geotiff_bytes(), modality="optical").json()
    response = query(client, [uploaded["asset_id"]], "Describe the land cover")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_KEYS
    assert body["task"] == "single_image"
    assert body["confidence"] == 0.0
    assert body["facts"] == {}
    assert body["overlay"] == {"type": "none", "file": None}
    assert "not connected" in body["answer_text"]
    assert any("No acquisition date" in warning for warning in body["warnings"])
    assert "no image analysis" in body["warnings"][-1]
    assert body["receipt"]["trace"][-1]["status"] == "stub"


def test_single_radar_description_is_not_mistaken_for_sensor_comparison(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    uploaded = upload(
        client,
        geotiff_bytes(bands=2, descriptions=["VV", "VH"]),
    ).json()
    response = query(client, [uploaded["asset_id"]], "Describe this radar scene")
    assert response.status_code == 200
    assert response.json()["task"] == "single_image"


def test_two_optical_files_can_use_the_word_optical_without_false_rejection(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    before = upload(
        client,
        geotiff_bytes(width=256, height=256),
        modality="optical",
        acquisition_date="2020-01-01",
    ).json()
    after = upload(
        client,
        geotiff_bytes(width=256, height=256),
        modality="optical",
        acquisition_date="2021-01-01",
    ).json()
    response = query(
        client,
        [before["asset_id"], after["asset_id"]],
        "Compare these optical images",
    )
    assert response.status_code == 200
    assert response.json()["task"] == "change"


def test_change_route_orders_assets_by_date(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    later = upload(
        client,
        geotiff_bytes(width=256, height=256),
        modality="optical",
        acquisition_date="2025-05-06",
    ).json()
    earlier = upload(
        client,
        geotiff_bytes(width=256, height=256),
        modality="optical",
        acquisition_date="2020-01-02",
    ).json()
    response = query(
        client,
        [later["asset_id"], earlier["asset_id"]],
        "Has the built-up area changed?",
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_KEYS
    assert body["task"] == "change"
    assert body["parameters"]["before_asset_id"] == earlier["asset_id"]
    assert body["parameters"]["after_asset_id"] == later["asset_id"]
    assert body["parameters"]["before_date"] == "2020-01-02"
    assert body["parameters"]["after_date"] == "2025-05-06"


def test_optical_sar_route_is_independent_of_upload_order(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    sar = upload(
        client,
        geotiff_bytes(bands=2, descriptions=["VV", "VH"], tags={"units": "linear"}),
    ).json()
    optical = upload(client, geotiff_bytes(descriptions=["green", "nir", "swir"]), modality="optical").json()
    response = query(
        client,
        [sar["asset_id"], optical["asset_id"]],
        "Compare the optical and SAR sensors",
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_KEYS
    assert body["task"] == "optical_sar"
    assert body["parameters"]["optical_asset_id"] == optical["asset_id"]
    assert body["parameters"]["sar_asset_id"] == sar["asset_id"]


def test_mismatched_grid_returns_structured_rejection(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    first = upload(
        client,
        geotiff_bytes(),
        modality="optical",
        acquisition_date="2020-01-01",
    ).json()
    second = upload(
        client,
        geotiff_bytes(transform=from_origin(78.0, 29.0, 0.001, 0.001)),
        modality="optical",
        acquisition_date="2021-01-01",
    ).json()
    response = query(client, [first["asset_id"], second["asset_id"]], "What changed?")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_KEYS
    assert body["task"] == "reject"
    assert body["receipt"]["rejected"] is True
    assert body["parameters"]["rejection_code"] == "incompatible_grid"
    assert body["receipt"]["trace"][0]["stage"] == "checker"


def test_same_date_unknown_modality_and_question_mismatch_reject(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    first = upload(client, geotiff_bytes(), modality="optical", acquisition_date="2020-01-01").json()
    second = upload(client, geotiff_bytes(), modality="optical", acquisition_date="2020-01-01").json()
    same_date = query(client, [first["asset_id"], second["asset_id"]], "What changed?").json()
    assert same_date["task"] == "reject"
    assert same_date["parameters"]["rejection_code"] == "different_dates_required"

    unknown = upload(client, geotiff_bytes(bands=1)).json()
    unknown_result = query(client, [unknown["asset_id"]], "Describe it").json()
    assert unknown_result["parameters"]["rejection_code"] == "modality_required"

    mismatch = query(client, [first["asset_id"]], "What changed before and after?").json()
    assert mismatch["parameters"]["rejection_code"] == "question_input_mismatch"


def test_duplicate_asset_is_a_structured_rejection(
    client: TestClient, geotiff_bytes: Callable[..., bytes]
) -> None:
    asset = upload(client, geotiff_bytes(), modality="optical").json()
    response = query(client, [asset["asset_id"], asset["asset_id"]], "Describe these")
    assert response.status_code == 200
    assert response.json()["parameters"]["rejection_code"] == "duplicate_asset"


def test_unknown_asset_is_infrastructure_error(client: TestClient) -> None:
    response = query(client, ["00000000-0000-0000-0000-000000000001"], "Describe it")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset_not_found"


def test_request_validation_uses_error_envelope(client: TestClient) -> None:
    response = client.post("/query", json={"asset_ids": [], "question": " "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_openapi_exposes_the_three_public_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/upload", "/query"} <= set(paths)
