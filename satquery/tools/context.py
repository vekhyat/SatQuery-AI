"""Server-owned execution context; paths never come from the query text."""
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore

from satquery.storage import AssetStore


@dataclass(frozen=True)
class ToolContext:
    store: AssetStore
    output_dir: Path
    artifact_base_url: str
    slots: BoundedSemaphore
