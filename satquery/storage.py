from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile

from satquery.contracts import AssetRecord, RasterMetadata
from satquery.errors import SatQueryError

CHUNK_SIZE = 1024 * 1024


@dataclass(slots=True)
class PendingAsset:
    asset_id: UUID
    original_name: str
    stored_name: str
    path: Path
    size_bytes: int
    sha256: str


class AssetStore:
    def __init__(
        self,
        root: Path,
        max_upload_bytes: int,
        retention: timedelta,
    ) -> None:
        self.root = root.resolve()
        self.max_upload_bytes = max_upload_bytes
        self.retention = retention
        self.root.mkdir(parents=True, exist_ok=True)

    async def write_upload(self, upload: UploadFile) -> PendingAsset:
        original_name = Path(upload.filename or "").name
        if not original_name:
            raise SatQueryError(422, "missing_filename", "The upload needs a filename.")
        if Path(original_name).suffix.lower() not in {".tif", ".tiff"}:
            raise SatQueryError(
                415,
                "unsupported_media_type",
                "Only .tif and .tiff GeoTIFF uploads are accepted.",
            )

        asset_id = uuid4()
        directory = self._asset_directory(asset_id)
        stored_name = "source.tif"
        path = directory / stored_name
        directory.mkdir(parents=False, exist_ok=False)
        digest = hashlib.sha256()
        size = 0

        try:
            with path.open("wb") as destination:
                while chunk := await upload.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise SatQueryError(
                            413,
                            "upload_too_large",
                            "The GeoTIFF exceeds the configured upload limit.",
                            {"max_bytes": self.max_upload_bytes},
                        )
                    digest.update(chunk)
                    destination.write(chunk)
            if size == 0:
                raise SatQueryError(422, "empty_upload", "The uploaded file is empty.")
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        return PendingAsset(
            asset_id=asset_id,
            original_name=original_name,
            stored_name=stored_name,
            path=path,
            size_bytes=size,
            sha256=digest.hexdigest(),
        )

    def finalize(self, pending: PendingAsset, metadata: RasterMetadata, warnings: list[str]) -> AssetRecord:
        created_at = datetime.now(UTC)
        record = AssetRecord(
            asset_id=pending.asset_id,
            original_name=pending.original_name,
            stored_name=pending.stored_name,
            size_bytes=pending.size_bytes,
            sha256=pending.sha256,
            created_at=created_at,
            expires_at=created_at + self.retention,
            metadata=metadata,
            warnings=warnings,
        )
        manifest_path = self._asset_directory(pending.asset_id) / "metadata.json"
        manifest_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return record

    def discard(self, asset_id: UUID) -> None:
        shutil.rmtree(self._asset_directory(asset_id), ignore_errors=True)

    def load(self, asset_id: UUID, now: datetime | None = None) -> AssetRecord:
        directory = self._asset_directory(asset_id)
        manifest_path = directory / "metadata.json"
        if not manifest_path.is_file():
            raise self._not_found()
        try:
            record = AssetRecord.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SatQueryError(
                500,
                "asset_manifest_invalid",
                "Stored asset metadata is unreadable.",
            ) from exc

        current_time = now or datetime.now(UTC)
        if record.expires_at <= current_time:
            self.discard(asset_id)
            raise self._not_found()
        if not (directory / record.stored_name).is_file():
            raise self._not_found()
        return record

    def cleanup_expired(self, now: datetime | None = None) -> int:
        current_time = now or datetime.now(UTC)
        removed = 0
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                asset_id = UUID(directory.name)
            except ValueError:
                continue
            manifest_path = directory / "metadata.json"
            if not manifest_path.is_file():
                continue
            try:
                record = AssetRecord.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if record.expires_at <= current_time:
                self.discard(asset_id)
                removed += 1
        return removed

    def source_path(self, record: AssetRecord) -> Path:
        path = (self._asset_directory(record.asset_id) / record.stored_name).resolve()
        if path.parent != self._asset_directory(record.asset_id):
            raise SatQueryError(500, "unsafe_asset_path", "Stored asset path is invalid.")
        return path

    def _asset_directory(self, asset_id: UUID) -> Path:
        directory = (self.root / str(asset_id)).resolve()
        if directory.parent != self.root:
            raise SatQueryError(500, "unsafe_asset_path", "Asset path escaped storage root.")
        return directory

    @staticmethod
    def _not_found() -> SatQueryError:
        return SatQueryError(
            404,
            "asset_not_found",
            "An asset ID is unknown or has expired.",
        )
