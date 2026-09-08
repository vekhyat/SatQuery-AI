from __future__ import annotations

import math

from satquery.contracts import RoutePlan, Task, ToolResult


def compose_answer(plan: RoutePlan, result: ToolResult) -> str:
    if plan.task is Task.OPTICAL_SAR and isinstance(result.facts.get("sar_contribution"), str):
        return "Water and built-up candidates from optical + SAR. " + result.facts["sar_contribution"]
    if plan.task is Task.CHANGE and plan.tool == "change_mci_v1":
        return _compose_change_answer(result)
    summary = result.facts.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return (
        f"The request was validated and routed to {plan.task.value}, but the specialist "
        "analysis tool is not connected yet."
    )


def _compose_change_answer(result: ToolResult) -> str:
    facts = result.facts
    caption = _caption_text(facts)
    sentences: list[str] = [caption] if caption else []

    changed_pixels = facts.get("changed_pixels")
    changed_percent = facts.get("changed_percent")
    if _is_number(changed_pixels) and _is_number(changed_percent):
        sentences.append(
            f"Changed pixels: {int(changed_pixels):,} ({changed_percent:.2f}% of valid pixels)."
        )

    if changed_pixels != 0:
        classes = facts.get("classes")
        if isinstance(classes, dict):
            class_parts: list[str] = []
            for key, label in (("road_change", "Road change"), ("building_change", "building change")):
                value = classes.get(key)
                if isinstance(value, dict) and _is_number(value.get("percent_of_valid_pixels")):
                    class_parts.append(
                        f"{label}: {value['percent_of_valid_pixels']:.2f}% of valid pixels"
                    )
            if class_parts:
                sentences.append("; ".join(class_parts) + ".")

    area = _area_sentence(facts)
    if area:
        sentences.append(area)

    if sentences:
        return " ".join(sentences)
    return "Change analysis completed."


def _caption_text(facts: dict[str, object]) -> str:
    caption = facts.get("caption")
    value = caption.get("text") if isinstance(caption, dict) else None
    if not isinstance(value, str) or not value.strip():
        value = facts.get("summary")
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _area_sentence(facts: dict[str, object]) -> str | None:
    area_m2 = facts.get("physical_area_m2")
    area_hectares = facts.get("physical_area_hectares")
    if not _is_number(area_m2) and not _is_number(area_hectares):
        return None
    if _is_number(area_m2) and _is_number(area_hectares):
        return f"Estimated changed area: {area_m2:,.0f} m² ({area_hectares:.2f} ha)."
    if _is_number(area_m2):
        return f"Estimated changed area: {area_m2:,.0f} m²."
    return f"Estimated changed area: {area_hectares:.2f} ha."


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
