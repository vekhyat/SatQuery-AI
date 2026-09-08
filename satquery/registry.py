from __future__ import annotations

from collections.abc import Callable, Mapping

from satquery.contracts import AssetRecord, RoutePlan, ToolResult
from satquery.errors import SatQueryError
from satquery.tools.change_mci import build_change_mci_v1, change_mci_v1
from satquery.tools.context import ToolContext
from satquery.tools.mci_worker_client import MCIWorkerClient
from satquery.tools.optical_sar import optical_sar_v1

ToolHandler = Callable[[list[AssetRecord], RoutePlan, ToolContext | None], ToolResult]
STUB_TOOLS = frozenset({"single_image_stub_v0", "change_stub_v0"})


def _stub(name: str) -> ToolHandler:
    def run(_assets: list[AssetRecord], _plan: RoutePlan, _context: ToolContext | None = None) -> ToolResult:
        return ToolResult(
            facts={},
            confidence=0.0,
            warnings=[
                f"{name} is a routing stub; no image analysis has been performed."
            ],
        )

    return run


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "single_image_stub_v0": _stub("single_image_stub_v0"),
    "change_stub_v0": _stub("change_stub_v0"),
    "change_mci_v1": change_mci_v1,
    "optical_sar_v1": optical_sar_v1,
}


def build_tool_registry(mci_client: MCIWorkerClient) -> dict[str, ToolHandler]:
    """Bind process-owned dependencies without mutating the shared registry."""

    registry = dict(TOOL_REGISTRY)
    registry["change_mci_v1"] = build_change_mci_v1(lambda: mci_client)
    return registry


def is_stub_tool(tool_name: str) -> bool:
    return tool_name in STUB_TOOLS


def execute_tool(
    tool_name: str,
    assets: list[AssetRecord],
    plan: RoutePlan,
    context: ToolContext | None = None,
    *,
    registry: Mapping[str, ToolHandler] | None = None,
) -> ToolResult:
    handler = (registry or TOOL_REGISTRY).get(tool_name)
    if handler is None:
        raise SatQueryError(
            500,
            "tool_not_registered",
            "The router selected a tool outside the versioned registry.",
        )
    return handler(assets, plan, context)
