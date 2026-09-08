"""High-level standalone bi-temporal change-analysis specialist."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol

from .analysis import (
    compute_change_statistics,
    extract_change_components,
    physical_area_from_metadata,
)
from .artifacts import create_unique_output_directory, write_evidence_artifacts
from .mci_inference import MCIPrediction
from .result import CaptionEvidence, ConfidenceProvenance, Timing, Tool2Result


class InferenceRuntime(Protocol):
    checkpoint_path: Path
    device: Any
    load_status: dict[str, dict[str, list[str]]]

    def predict(self, image_a_path: str | Path, image_b_path: str | Path) -> MCIPrediction:
        ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_status_summary(
    load_status: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, int | bool]]:
    return {
        name: {
            "loaded": len(status["missing_keys"]) == 0,
            "missing_key_count": len(status["missing_keys"]),
            "unexpected_key_count": len(status["unexpected_keys"]),
        }
        for name, status in load_status.items()
    }


class ChangeAnalysisTool:
    """Turn one reusable MCI runtime prediction into a complete Tool 2 result."""

    def __init__(
        self,
        runtime: InferenceRuntime,
        component_min_pixels: int = 6,
        component_connectivity: int = 8,
        overlay_alpha: float = 0.45,
        default_output_root: str | Path | None = None,
    ) -> None:
        if not 0.0 <= overlay_alpha <= 1.0:
            raise ValueError("overlay_alpha must be between 0 and 1")
        self.runtime = runtime
        self.component_min_pixels = component_min_pixels
        self.component_connectivity = component_connectivity
        self.overlay_alpha = overlay_alpha
        self.default_output_root = Path(
            default_output_root
            if default_output_root is not None
            else Path(__file__).resolve().parents[2] / "outputs" / "tool2"
        ).resolve()
        self.checkpoint_sha256 = _sha256(Path(runtime.checkpoint_path).resolve())

    def analyze(
        self,
        before_path: str | Path,
        after_path: str | Path,
        question: str | None = None,
        geo_metadata: dict[str, Any] | None = None,
        output_dir: str | Path | None = None,
        job_id: str | None = None,
    ) -> Tool2Result:
        before = Path(before_path).resolve()
        after = Path(after_path).resolve()
        if not before.is_file():
            raise FileNotFoundError(before)
        if not after.is_file():
            raise FileNotFoundError(after)

        prediction = self.runtime.predict(before, after)
        postprocessing_started = time.perf_counter()
        statistics = compute_change_statistics(prediction.mask)
        components = extract_change_components(
            prediction.mask,
            min_pixels=self.component_min_pixels,
            connectivity=self.component_connectivity,
        )
        area, geospatial_warning = physical_area_from_metadata(
            statistics["changed_pixels"], geo_metadata
        )

        analysis_dir = create_unique_output_directory(
            output_dir if output_dir is not None else self.default_output_root,
            job_id if job_id is not None else before.stem,
        )
        evidence = write_evidence_artifacts(
            analysis_dir=analysis_dir,
            before_path=before,
            after_path=after,
            semantic_mask=prediction.mask,
            components=components,
            overlay_alpha=self.overlay_alpha,
        )

        warnings = [
            "Connected regions are semantic change clusters, not road or building instance counts."
        ]
        if geospatial_warning is not None:
            warnings.append(geospatial_warning)
        if question is not None:
            warnings.append(
                "The supplied question is retained as context only; the MCI caption is not question-conditioned."
            )

        caption = CaptionEvidence(text=prediction.caption)
        facts = {
            "summary": prediction.caption,
            "caption": {
                "text": caption.text,
                "source": caption.source,
                "question_conditioned": caption.question_conditioned,
            },
            **statistics,
            "components": components,
            **area,
        }
        postprocessing_seconds = time.perf_counter() - postprocessing_started
        result = Tool2Result(
            task="change_analysis",
            input={
                "before": str(before),
                "after": str(after),
                "question": question,
                "geospatial_metadata_available": geo_metadata is not None,
            },
            model={
                "name": "Change-Agent MCI",
                "checkpoint_path": str(Path(self.runtime.checkpoint_path).resolve()),
                "checkpoint_sha256": self.checkpoint_sha256,
                "device": str(self.runtime.device),
                "question_conditioned": False,
                "state_dicts": _load_status_summary(self.runtime.load_status),
            },
            facts=facts,
            confidence=ConfidenceProvenance(),
            warnings=warnings,
            evidence=evidence,
            timing=Timing(
                inference_seconds=prediction.inference_seconds,
                postprocessing_seconds=postprocessing_seconds,
                total_seconds=prediction.inference_seconds + postprocessing_seconds,
            ),
        )
        Path(evidence["result"]).write_text(
            json.dumps(result.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        return result
