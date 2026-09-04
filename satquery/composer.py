from __future__ import annotations

from satquery.contracts import RoutePlan, ToolResult


def compose_answer(plan: RoutePlan, result: ToolResult) -> str:
    summary = result.facts.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return (
        f"The request was validated and routed to {plan.task.value}, but the specialist "
        "analysis tool is not connected yet."
    )
