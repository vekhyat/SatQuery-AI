"""Server-owned execution context; paths never come from the query text."""
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore

from satquery.contracts import Task
from satquery.storage import AssetStore


@dataclass(frozen=True)
class ToolContext:
    store: AssetStore
    output_dir: Path
    artifact_base_url: str
    slots: BoundedSemaphore


_TASK_LAYOUT = {
    Task.SINGLE_IMAGE: ("tool1-results", "tool1"),
    Task.CHANGE: ("tool2-results", "tool2"),
    Task.OPTICAL_SAR: ("tool3-results", "tool3"),
}


def build_tool_context(
    *,
    task: Task,
    store: AssetStore,
    artifact_root_url: str,
    slots: BoundedSemaphore,
) -> ToolContext:
    try:
        output_name, url_segment = _TASK_LAYOUT[task]
    except KeyError as exc:
        raise ValueError(f"Task {task.value!r} does not have a specialist execution context.")
    normalized_root = artifact_root_url.rstrip("/")
    if normalized_root.endswith(("/tool1", "/tool2", "/tool3")):
        raise ValueError("artifact_root_url must be the shared artifact root, not a specialist URL.")
    return ToolContext(
        store=store,
        output_dir=store.root / output_name,
        artifact_base_url=f"{normalized_root}/{url_segment}",
        slots=slots,
    )
