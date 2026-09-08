from datetime import timedelta
from threading import BoundedSemaphore

import pytest

from satquery.contracts import RoutePlan, Task
from satquery import errors
from satquery.storage import AssetStore
from satquery.tools.context import ToolContext
from satquery.tools.optical_sar import ToolInputError, optical_sar_v1


def test_tool_execution_error_carries_safe_execution_semantics():
    error = errors.ToolExecutionError(
        503,
        "WORKER_UNAVAILABLE",
        "The specialist worker is unavailable.",
        retryable=True,
    )

    assert isinstance(error, errors.SatQueryError)
    assert error.status_code == 503
    assert error.http_status == 503
    assert error.code == "WORKER_UNAVAILABLE"
    assert error.message == "The specialist worker is unavailable."
    assert error.retryable is True
    assert error.as_rejection is False
    assert error.details == {}


def test_tool3_input_error_keeps_its_existing_public_contract_as_a_rejection():
    error = ToolInputError("Missing required bands.")

    assert isinstance(error, errors.ToolExecutionError)
    assert error.status_code == 422
    assert error.code == "tool3_invalid_dataset"
    assert error.message == "Missing required bands."
    assert error.as_rejection is True
    assert error.retryable is False


def test_tool3_context_and_busy_failures_use_generic_execution_error(tmp_path):
    plan = RoutePlan(
        task=Task.OPTICAL_SAR,
        tool="optical_sar_v1",
        ordered_asset_ids=[],
        parameters={},
        why="test",
    )
    with pytest.raises(errors.ToolExecutionError) as missing:
        optical_sar_v1([], plan, None)
    assert missing.value.status_code == 500
    assert missing.value.code == "missing_tool_context"
    assert missing.value.as_rejection is False

    store = AssetStore(tmp_path / "uploads", 1024, timedelta(hours=1))
    slots = BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    context = ToolContext(
        store=store,
        output_dir=store.root / "tool3-results",
        artifact_base_url="/artifacts/tool3",
        slots=slots,
    )
    try:
        with pytest.raises(errors.ToolExecutionError) as busy:
            optical_sar_v1([], plan, context)
    finally:
        slots.release()
    assert busy.value.status_code == 429
    assert busy.value.code == "tool3_busy"
    assert busy.value.retryable is True
    assert busy.value.as_rejection is False
