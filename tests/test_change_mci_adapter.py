"""Main-side adapter tests with trusted storage and no live worker."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import BoundedSemaphore

from satquery.contracts import (
    AssetRecord,
    Bounds,
    MetadataProvenance,
    Modality,
    RasterMetadata,
    RoutePlan,
    Task,
    ValueProvenance,
)
from satquery.storage import AssetStore
from satquery.tools.change_mci import ChangeMCIAdapterError, build_change_mci_v1
from satquery.tools.change_mci_protocol import ChangeAnalysisSuccessResponse
from satquery.tools.context import ToolContext
from tests.test_change_mci_client import success_payload


class FakeWorkerClient:
    def __init__(self, output_root: Path, *, mismatched_request_id: bool = False, missing_artifact: bool = False, warning: str | None = None) -> None:
        self.output_root = output_root
        self.mismatched_request_id = mismatched_request_id
        self.missing_artifact = missing_artifact
        self.warning = warning
        self.request = None

    def analyze(self, request):
        self.request = request
        run_id = "a" * 32
        directory = self.output_root / run_id
        directory.mkdir(parents=True, exist_ok=True)
        for filename in (
            "semantic_mask_raw.png",
            "semantic_mask_rgb.png",
            "change_binary_mask.png",
            "overlay.png",
            "components.json",
        ):
            if not (self.missing_artifact and filename == "overlay.png"):
                (directory / filename).write_bytes(b"artifact")
        if self.missing_artifact:
            (directory / "overlay.png").unlink(missing_ok=True)
        response_id = str(uuid.uuid4()) if self.mismatched_request_id else str(request.request_id)
        payload = success_payload(response_id)
        if self.warning is not None:
            payload["warnings"] = [self.warning]
        return ChangeAnalysisSuccessResponse.model_validate(payload)


class ChangeMCIAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = AssetStore(self.root / "uploads", 2_000_000, timedelta(hours=1))
        self.output_root = self.root / "tool2-output"
        self.context = ToolContext(
            store=self.store,
            output_dir=self.output_root,
            artifact_base_url="/artifacts/tool2",
            slots=BoundedSemaphore(1),
        )
        self.before = self._asset("before.tif")
        self.after = self._asset("after.tif")
        self.plan = RoutePlan(
            task=Task.CHANGE,
            tool="change_mci_v1",
            ordered_asset_ids=[self.before.asset_id, self.after.asset_id],
            parameters={"before_asset_id": str(self.before.asset_id), "after_asset_id": str(self.after.asset_id)},
            why="test",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _asset(self, name: str, *, width: int = 256, band_count: int = 3, dtype: str = "uint8") -> AssetRecord:
        asset_id = uuid.uuid4()
        directory = self.store.root / str(asset_id)
        directory.mkdir()
        (directory / "source.tif").write_bytes(b"trusted test geotiff")
        provenance = MetadataProvenance(
            modality=ValueProvenance(source="user"),
            acquisition_date=ValueProvenance(source="user"),
        )
        metadata = RasterMetadata(
            driver="GTiff", width=width, height=256, band_count=band_count,
            dtypes=[dtype] * band_count, crs="EPSG:32643",
            bounds=Bounds(left=500000, bottom=3100000, right=500256, top=3100256),
            transform=[1, 0, 500000, 0, -1, 3100256], resolution=[1, 1], nodata=None,
            band_descriptions=["red", "green", "blue"][:band_count], tags={},
            modality=Modality.OPTICAL, acquisition_date=datetime(2020, 1, 1, tzinfo=UTC).date(),
            provenance=provenance,
        )
        now = datetime.now(UTC)
        return AssetRecord(
            asset_id=asset_id, original_name=name, stored_name="source.tif", size_bytes=1,
            sha256="a" * 64, created_at=now, expires_at=now + timedelta(hours=1),
            metadata=metadata, warnings=[],
        )

    def _handler(self, fake: FakeWorkerClient):
        return build_change_mci_v1(lambda: fake)

    def test_maps_ordered_assets_worker_facts_urls_and_access_manifest(self) -> None:
        fake = FakeWorkerClient(self.output_root)
        result = self._handler(fake)([self.after, self.before], self.plan, self.context)

        self.assertEqual(fake.request.before_path, str(self.store.source_path(self.before)))
        self.assertEqual(fake.request.after_path, str(self.store.source_path(self.after)))
        self.assertEqual(fake.request.geo_metadata["validated"], True)
        self.assertNotIn("question", fake.request.model_dump())
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.facts["confidence_status"], "not_measured")
        self.assertEqual(result.facts["classes"]["building_change"]["pixel_count"], 500)
        self.assertEqual(result.overlay.file, "/artifacts/tool2/" + "a" * 32 + "/overlay.png")
        self.assertNotIn(str(self.root), json.dumps(result.model_dump()))
        access = json.loads((self.output_root / ("a" * 32) / "access.json").read_text())
        self.assertEqual(access["asset_ids"], [str(self.before.asset_id), str(self.after.asset_id)])
        self.assertNotIn("source", json.dumps(access).lower())

    def test_rejects_missing_context_wrong_task_bad_assets_and_inconsistent_plan(self) -> None:
        fake = FakeWorkerClient(self.output_root)
        handler = self._handler(fake)
        bad_task = self.plan.model_copy(update={"task": Task.SINGLE_IMAGE})
        bad_parameters = self.plan.model_copy(update={"parameters": {"before_asset_id": str(self.after.asset_id)}})
        for assets, plan, context in (
            ([self.before, self.after], self.plan, None),
            ([self.before, self.after], bad_task, self.context),
            ([self.before], self.plan, self.context),
            ([self.before, self.after], bad_parameters, self.context),
        ):
            with self.subTest(plan=plan.task):
                with self.assertRaises(ChangeMCIAdapterError):
                    handler(assets, plan, context)

    def test_rejects_incompatible_metadata_missing_artifacts_and_request_mismatch(self) -> None:
        for invalid in (
            self._asset("bad-size.tif", width=255),
            self._asset("bad-bands.tif", band_count=1),
            self._asset("bad-dtype.tif", dtype="uint16"),
        ):
            plan = self.plan.model_copy(update={"ordered_asset_ids": [invalid.asset_id, self.after.asset_id], "parameters": {"before_asset_id": str(invalid.asset_id), "after_asset_id": str(self.after.asset_id)}})
            with self.subTest(invalid=invalid.original_name):
                with self.assertRaises(ChangeMCIAdapterError):
                    self._handler(FakeWorkerClient(self.output_root))([invalid, self.after], plan, self.context)

        with self.assertRaises(ChangeMCIAdapterError):
            self._handler(FakeWorkerClient(self.output_root, mismatched_request_id=True))([self.before, self.after], self.plan, self.context)
        with self.assertRaises(ChangeMCIAdapterError):
            self._handler(FakeWorkerClient(self.output_root, missing_artifact=True))([self.before, self.after], self.plan, self.context)

    def test_preserves_safe_warnings_but_filters_path_like_warning_text(self) -> None:
        result = self._handler(FakeWorkerClient(self.output_root, warning=r"C:\private\source.tif"))(
            [self.before, self.after], self.plan, self.context
        )
        self.assertFalse(any("private" in warning.lower() for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
