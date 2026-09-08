from __future__ import annotations

from satquery.composer import compose_answer
from satquery.contracts import RoutePlan, Task, ToolResult


def _plan(task: Task, tool: str | None = "change_mci_v1") -> RoutePlan:
    return RoutePlan(
        task=task,
        tool=tool,
        ordered_asset_ids=[],
        parameters={},
        why="test",
    )


def _result(**facts) -> ToolResult:
    return ToolResult(facts=facts)


def test_change_composer_formats_caption_and_verified_class_statistics():
    result = _result(
        caption={"text": "the vegetation has been removed and a road with villas built along appears"},
        summary="unused summary",
        changed_pixels=19938,
        changed_percent=30.4229736328125,
        valid_pixels=65536,
        classes={
            "road_change": {"percent_of_valid_pixels": 11.263427734375},
            "building_change": {"percent_of_valid_pixels": 19.1595458984375},
        },
    )

    answer = compose_answer(_plan(Task.CHANGE), result)

    assert answer == (
        "The vegetation has been removed and a road with villas built along appears. "
        "Changed pixels: 19,938 (30.42% of valid pixels). "
        "Road change: 11.26% of valid pixels; building change: 19.16% of valid pixels."
    )


def test_change_composer_handles_no_change_without_zero_class_noise():
    result = _result(
        caption={"text": "the scene is the same as before"},
        changed_pixels=0,
        changed_percent=0.0,
        valid_pixels=65536,
        classes={
            "road_change": {"percent_of_valid_pixels": 0.0},
            "building_change": {"percent_of_valid_pixels": 0.0},
        },
    )

    answer = compose_answer(_plan(Task.CHANGE), result)

    assert answer == "The scene is the same as before. Changed pixels: 0 (0.00% of valid pixels)."
    assert "Road change" not in answer
    assert "building change" not in answer


def test_change_composer_includes_only_provided_physical_area():
    result = _result(
        caption={"text": "new development is visible"},
        changed_pixels=100,
        changed_percent=1.0,
        valid_pixels=10000,
        physical_area_m2=12500.0,
        physical_area_hectares=1.25,
    )

    answer = compose_answer(_plan(Task.CHANGE), result)

    assert answer.endswith("Estimated changed area: 12,500 m² (1.25 ha).")


def test_change_composer_omits_unavailable_area_and_confidence_sentinel():
    result = _result(
        caption={"text": "change detected"},
        changed_pixels=10,
        changed_percent=2.0,
        valid_pixels=500,
        physical_area_m2=None,
        physical_area_hectares=None,
        confidence_status="not_measured",
    )

    answer = compose_answer(_plan(Task.CHANGE), result)

    assert "area" not in answer.lower()
    assert "confidence" not in answer.lower()
    assert "0% confidence" not in answer.lower()


def test_change_composer_describes_classes_without_inferring_temporal_direction():
    result = _result(
        caption={"text": "semantic changes were detected"},
        changed_pixels=20,
        changed_percent=2.0,
        valid_pixels=1000,
        classes={
            "road_change": {"percent_of_valid_pixels": 1.1},
            "building_change": {"percent_of_valid_pixels": 0.9},
        },
    )

    answer = compose_answer(_plan(Task.CHANGE), result)

    assert "Road change: 1.10% of valid pixels" in answer
    assert "building change: 0.90% of valid pixels" in answer
    for directional_word in ("constructed", "demolished", "increased", "decreased"):
        assert directional_word not in answer.lower()


def test_change_composer_does_not_turn_components_into_object_counts():
    result = _result(
        caption={"text": "semantic changes were detected"},
        changed_pixels=20,
        changed_percent=2.0,
        valid_pixels=1000,
        classes={},
        components={
            "road_change": {"filtered_component_count": 12},
            "building_change": {"filtered_component_count": 34},
        },
    )

    answer = compose_answer(_plan(Task.CHANGE), result)

    assert "12" not in answer
    assert "34" not in answer
    assert "object" not in answer.lower()


def test_change_composer_falls_back_gracefully_when_optional_facts_are_missing():
    result = _result(summary="a concise model summary")

    assert compose_answer(_plan(Task.CHANGE), result) == "A concise model summary."


def test_tool3_composer_wording_remains_unchanged():
    result = _result(
        summary="ignored",
        sar_contribution="SAR adds water candidates.",
    )

    assert compose_answer(_plan(Task.OPTICAL_SAR, "optical_sar_v1"), result) == (
        "Water and built-up candidates from optical + SAR. SAR adds water candidates."
    )


def test_rejected_plan_composition_remains_summary_based():
    result = _result(summary="The request is unsupported.")

    assert compose_answer(_plan(Task.REJECT, None), result) == "The request is unsupported."
