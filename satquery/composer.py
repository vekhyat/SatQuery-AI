from __future__ import annotations

from satquery.contracts import RoutePlan, Task, ToolResult


def compose_answer(plan: RoutePlan, result: ToolResult) -> str:
    if plan.task is Task.OPTICAL_SAR and isinstance(result.facts.get("sar_contribution"), str):
        return "Water and built-up candidates from optical + SAR. " + result.facts["sar_contribution"]
    summary = result.facts.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return (
        f"The request was validated and routed to {plan.task.value}, but the specialist "
        "analysis tool is not connected yet."
    )
