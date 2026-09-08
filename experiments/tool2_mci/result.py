"""Stable standalone result types for Tool 2 Phase 2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CaptionEvidence:
    text: str
    source: str = "Change-Agent MCI decoder"
    question_conditioned: bool = False


@dataclass(frozen=True)
class ConfidenceProvenance:
    score: None = None
    type: str = "unavailable"
    source: str = "model_does_not_expose_calibrated_confidence"
    note: str = (
        "Change-Agent MCI inference currently provides class predictions and "
        "caption output but no calibrated overall confidence."
    )


@dataclass(frozen=True)
class Timing:
    inference_seconds: float
    postprocessing_seconds: float
    total_seconds: float


@dataclass(frozen=True)
class Tool2Result:
    task: str
    input: dict[str, Any]
    model: dict[str, Any]
    facts: dict[str, Any]
    confidence: ConfidenceProvenance
    warnings: list[str]
    evidence: dict[str, str]
    timing: Timing

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
