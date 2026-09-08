from datetime import timedelta
from threading import BoundedSemaphore

import pytest

from satquery.contracts import Task
from satquery.service import SatQueryService
from satquery.storage import AssetStore
from satquery.tools import context as context_module


def test_tool3_context_preserves_existing_storage_url_and_shared_objects(tmp_path):
    store = AssetStore(tmp_path / "uploads", 1024, timedelta(hours=1))
    slots = BoundedSemaphore(1)

    context = context_module.build_tool_context(
        task=Task.OPTICAL_SAR,
        store=store,
        artifact_root_url="/artifacts",
        slots=slots,
    )

    assert context.store is store
    assert context.output_dir == store.root / "tool3-results"
    assert context.artifact_base_url == "/artifacts/tool3"
    assert context.slots is slots


def test_tool2_context_uses_its_own_storage_and_url_with_shared_objects(tmp_path):
    store = AssetStore(tmp_path / "uploads", 1024, timedelta(hours=1))
    slots = BoundedSemaphore(1)

    context = context_module.build_tool_context(
        task=Task.CHANGE,
        store=store,
        artifact_root_url="/artifacts",
        slots=slots,
    )

    assert context.store is store
    assert context.output_dir == store.root / "tool2-results"
    assert context.artifact_base_url == "/artifacts/tool2"
    assert context.slots is slots


@pytest.mark.parametrize(
    ("task", "expected_url"),
    [
        (Task.OPTICAL_SAR, "/api/artifacts/tool3"),
        (Task.CHANGE, "/api/artifacts/tool2"),
    ],
)
def test_context_preserves_mount_prefix_without_duplicate_slashes(
    tmp_path, task, expected_url
):
    store = AssetStore(tmp_path / task.value, 1024, timedelta(hours=1))

    context = context_module.build_tool_context(
        task=task,
        store=store,
        artifact_root_url="/api/artifacts/",
        slots=BoundedSemaphore(1),
    )

    assert context.artifact_base_url == expected_url


@pytest.mark.parametrize("task", [Task.SINGLE_IMAGE, Task.REJECT])
def test_context_rejects_tasks_without_specialist_artifacts(tmp_path, task):
    store = AssetStore(tmp_path / task.value, 1024, timedelta(hours=1))

    with pytest.raises(ValueError, match="does not have a specialist execution context"):
        context_module.build_tool_context(
            task=task,
            store=store,
            artifact_root_url="/artifacts",
            slots=BoundedSemaphore(1),
        )


def test_context_rejects_an_already_specialist_suffixed_artifact_root(tmp_path):
    store = AssetStore(tmp_path / "uploads", 1024, timedelta(hours=1))

    with pytest.raises(ValueError, match="shared artifact root"):
        context_module.build_tool_context(
            task=Task.OPTICAL_SAR,
            store=store,
            artifact_root_url="/artifacts/tool3",
            slots=BoundedSemaphore(1),
        )


def test_service_constructs_task_contexts_and_preserves_legacy_tool3_default(tmp_path):
    store = AssetStore(tmp_path / "uploads", 1024, timedelta(hours=1))
    service = SatQueryService(store)

    legacy_tool3 = service.tool_context()
    tool2 = service.tool_context(Task.CHANGE, artifact_root_url="/api/artifacts/")

    assert legacy_tool3.output_dir == store.root / "tool3-results"
    assert legacy_tool3.artifact_base_url == "/artifacts/tool3"
    assert legacy_tool3.slots is service.tool_slots
    assert tool2.output_dir == store.root / "tool2-results"
    assert tool2.artifact_base_url == "/api/artifacts/tool2"
    assert tool2.slots is service.tool_slots
