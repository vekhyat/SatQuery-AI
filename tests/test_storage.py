from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import Settings, create_app
from tests.test_api import upload


def test_cleanup_removes_only_expired_uuid_directories(
    client: TestClient,
    geotiff_bytes: Callable[..., bytes],
    settings: Settings,
) -> None:
    uploaded = upload(client, geotiff_bytes(), modality="optical").json()
    store = client.app.state.store
    record = store.load(uploaded["asset_id"])

    unrelated = settings.runtime_dir / "do-not-delete"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

    removed = store.cleanup_expired(now=record.expires_at + timedelta(seconds=1))
    assert removed == 1
    assert not (settings.runtime_dir / uploaded["asset_id"]).exists()
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_expired_asset_returns_404(
    tmp_path: Path, geotiff_bytes: Callable[..., bytes]
) -> None:
    settings = Settings(
        runtime_dir=tmp_path / "expired-runtime",
        max_upload_bytes=2 * 1024 * 1024,
        retention_hours=0,
    )
    with TestClient(create_app(settings)) as client:
        uploaded = upload(client, geotiff_bytes(), modality="optical").json()
        response = client.post(
            "/query",
            json={"asset_ids": [uploaded["asset_id"]], "question": "Describe it"},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset_not_found"
