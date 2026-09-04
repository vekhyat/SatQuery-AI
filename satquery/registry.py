from __future__ import annotations

from collections.abc import Callable

from satquery.contracts import AssetRecord, RoutePlan, ToolResult
from satquery.errors import SatQueryError

ToolHandler = Callable[[list[AssetRecord], RoutePlan], ToolResult]


def _stub(name: str) -> ToolHandler:
    def run(_assets: list[AssetRecord], _plan: RoutePlan) -> ToolResult:
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
    "optical_sar_stub_v0": _stub("optical_sar_stub_v0"),
}


def execute_tool(
    tool_name: str, assets: list[AssetRecord], plan: RoutePlan
) -> ToolResult:
    handler = TOOL_REGISTRY.get(tool_name)
    if handler is None:
        raise SatQueryError(
            500,
            "tool_not_registered",
            "The router selected a tool outside the versioned registry.",
        )
    return handler(assets, plan)
