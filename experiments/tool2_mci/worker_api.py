"""Local-only FastAPI boundary for the frozen Tool 2 MCI runtime."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError

from satquery.tools.change_mci_protocol import (
    CONTRACT_VERSION,
    ArtifactFilenames,
    CaptionResponse,
    ChangeAnalysisErrorResponse,
    ChangeAnalysisRequest,
    ChangeAnalysisSuccessResponse,
    ClassStatisticsResponse,
    ComponentGroupResponse,
    ComponentItemResponse,
    ComponentsResponse,
    ConfidenceResponse,
    GeospatialResponse,
    HealthResponse,
    ModelMetadataResponse,
    NotReadyResponse,
    ReadyResponse,
    StatisticsResponse,
    TimingResponse,
    WorkerError,
)


LOGGER = logging.getLogger(__name__)
INTERNAL_ARTIFACT_FILENAMES = {
    "before": "before.png",
    "after": "after.png",
    "semantic_mask": "semantic_mask_raw.png",
    "semantic_mask_rgb": "semantic_mask_rgb.png",
    "binary_mask": "change_binary_mask.png",
    "overlay": "overlay.png",
    "components": "components.json",
    "result": "result.json",
}
PUBLIC_ARTIFACT_FILENAMES = {
    key: INTERNAL_ARTIFACT_FILENAMES[key]
    for key in (
        "semantic_mask",
        "semantic_mask_rgb",
        "binary_mask",
        "overlay",
        "components",
    )
}


class ChangeAnalyzer(Protocol):
    """Narrow boundary implemented by ChangeAnalysisTool and test fakes."""

    def analyze(
        self,
        before_path: Path,
        after_path: Path,
        *,
        geo_metadata: dict[str, Any] | None,
        output_dir: Path,
        job_id: str,
    ) -> Any:
        ...


class WorkerPhase(StrEnum):
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


class ImagePolicy(StrEnum):
    """Production GeoTIFF policy plus a test-only frozen LEVIR regression mode."""

    PRODUCTION_TIFF = "production_tiff"
    INTERNAL_LEVIR_PNG_REGRESSION = "internal_leviR_png_regression"


class UnsupportedImageError(ValueError):
    """An input cannot satisfy the frozen 256×256 RGB MCI boundary."""


@dataclass(frozen=True)
class WorkerConfig:
    """Server-owned worker configuration; request payloads cannot override it."""

    input_root: Path
    output_root: Path
    checkpoint: Path
    device: str = "cuda:0"
    host: str = "127.0.0.1"
    port: int = 8012
    busy_wait_seconds: float = 0.25

    def __post_init__(self) -> None:
        if not self.device.strip():
            raise ValueError("device must not be blank")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.busy_wait_seconds < 0:
            raise ValueError("busy_wait_seconds must be non-negative")
        object.__setattr__(self, "input_root", Path(self.input_root).resolve())
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())
        object.__setattr__(self, "checkpoint", Path(self.checkpoint).resolve())


@dataclass
class WorkerState:
    """Small, explicit lifecycle holder independent from FastAPI and MCI."""

    config: WorkerConfig
    phase: WorkerPhase = WorkerPhase.STARTING
    analyzer: ChangeAnalyzer | None = None
    ready_metadata: ReadyResponse | None = None
    failure: WorkerError | None = None
    slot: threading.BoundedSemaphore = field(
        default_factory=lambda: threading.BoundedSemaphore(1), repr=False
    )

    def mark_ready(
        self,
        analyzer: ChangeAnalyzer,
        *,
        model_name: str,
        checkpoint_sha256: str,
        vocab_size: int,
    ) -> None:
        self.analyzer = analyzer
        self.ready_metadata = ReadyResponse(
            model=model_name,
            device=self.config.device,
            checkpoint_sha256=checkpoint_sha256,
            vocab_size=vocab_size,
        )
        self.failure = None
        self.phase = WorkerPhase.READY

    def mark_failed(self, _safe_reason: str = "Worker initialization failed.") -> None:
        """Retain a generic externally safe failure; detailed cause remains in logs."""
        self.analyzer = None
        self.ready_metadata = None
        self.failure = WorkerError(
            code="MODEL_NOT_READY",
            message="The MCI model is not ready.",
            retryable=False,
        )
        self.phase = WorkerPhase.FAILED

    def readiness(self) -> ReadyResponse | NotReadyResponse:
        if self.phase is WorkerPhase.READY and self.ready_metadata is not None:
            return self.ready_metadata
        return NotReadyResponse(
            error=self.failure
            or WorkerError(
                code="MODEL_NOT_READY",
                message="The MCI model is still starting.",
                retryable=False,
            )
        )


def _error_response(
    status_code: int,
    code: WorkerError["code"],
    message: str,
    *,
    retryable: bool = False,
    request_id: Any = None,
) -> JSONResponse:
    body = ChangeAnalysisErrorResponse(
        request_id=request_id,
        error=WorkerError(code=code, message=message, retryable=retryable),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _contained_existing_input(path_value: str, input_root: Path) -> Path:
    candidate = Path(path_value)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise FileNotFoundError from error
    if not resolved.is_file():
        raise FileNotFoundError
    try:
        resolved.relative_to(input_root.resolve(strict=True))
    except ValueError as error:
        raise ValueError("outside configured input root") from error
    return resolved


def _validate_mci_image_pair(
    before: Path,
    after: Path,
    *,
    image_policy: ImagePolicy,
) -> None:
    """Enforce the production TIFF boundary before a model runtime receives input."""
    try:
        with Image.open(before) as before_image, Image.open(after) as after_image:
            images = (before_image, after_image)
            if image_policy is ImagePolicy.PRODUCTION_TIFF:
                if any(path.suffix.lower() not in {".tif", ".tiff"} for path in (before, after)):
                    raise UnsupportedImageError
                if any(image.format != "TIFF" for image in images):
                    raise UnsupportedImageError
                for image in images:
                    bits_per_sample = image.tag_v2.get(258) if hasattr(image, "tag_v2") else None
                    if tuple(bits_per_sample or ()) != (8, 8, 8):
                        raise UnsupportedImageError
            if before_image.mode != "RGB" or after_image.mode != "RGB":
                raise UnsupportedImageError
            if before_image.size != (256, 256) or after_image.size != (256, 256):
                raise UnsupportedImageError
    except (UnidentifiedImageError, OSError) as error:
        raise UnsupportedImageError from error


def _component_group(raw: dict[str, Any]) -> ComponentGroupResponse:
    items = raw.get("items", raw.get("components", []))
    top_components = [
        ComponentItemResponse(
            component_id=item["component_id"],
            class_name=item.get("class_name", item.get("class", "all_changed")),
            class_id=item.get("class_id"),
            pixel_area=item["pixel_area"],
            bounding_box_pixels=item.get("bounding_box_pixels", {}),
            centroid_pixels=item.get("centroid_pixels", {}),
            percent_of_total_changed_pixels=item.get(
                "percent_of_total_changed_pixels", 0.0
            ),
        )
        for item in items[:10]
    ]
    return ComponentGroupResponse(
        raw_component_count=raw["raw_component_count"],
        filtered_component_count=raw["filtered_component_count"],
        filtered_pixel_count=raw["filtered_pixel_count"],
        largest_component_pixels=raw.get("largest_component_pixels"),
        top_components=top_components,
    )


def _sanitize_artifacts(evidence: dict[str, str], output_root: Path) -> tuple[str, ArtifactFilenames]:
    try:
        result_path = Path(evidence["result"]).resolve(strict=True)
        run_directory = result_path.parent
        run_directory.relative_to(output_root.resolve(strict=True))
        run_id = run_directory.name
        if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
            raise ValueError("worker run ID is invalid")
        sanitized: dict[str, str] = {}
        for name, expected_filename in INTERNAL_ARTIFACT_FILENAMES.items():
            artifact = Path(evidence[name]).resolve(strict=True)
            if artifact.parent != run_directory or artifact.name != expected_filename:
                raise ValueError("artifact is outside the worker-owned run directory")
            if name in PUBLIC_ARTIFACT_FILENAMES:
                sanitized[name] = artifact.name
        return run_id, ArtifactFilenames(**sanitized)
    except (KeyError, FileNotFoundError, ValueError) as error:
        raise ValueError("invalid artifact boundary") from error


def _success_response(result: Any, request_id: Any, output_root: Path) -> ChangeAnalysisSuccessResponse:
    payload = result.to_dict()
    facts = payload["facts"]
    classes = facts["classes"]
    per_class = {
        name: ClassStatisticsResponse(
            class_id=entry["class_id"],
            label=entry["label"],
            pixel_count=entry["pixel_count"],
            percent_of_valid_pixels=entry["percent_of_valid_pixels"],
            percent_of_changed_pixels=entry.get("percent_of_changed_pixels"),
        )
        for name, entry in classes.items()
    }
    components = facts["components"]
    run_id, artifacts = _sanitize_artifacts(payload["evidence"], output_root)
    return ChangeAnalysisSuccessResponse(
        request_id=request_id,
        run_id=run_id,
        caption=CaptionResponse(**facts["caption"]),
        statistics=StatisticsResponse(
            total_pixels=facts["total_pixels"],
            valid_pixels=facts["valid_pixels"],
            unchanged_pixels=facts["unchanged_pixels"],
            changed_pixels=facts["changed_pixels"],
            changed_fraction=facts["changed_fraction"],
            changed_percent=facts["changed_percent"],
            per_class=per_class,
        ),
        components=ComponentsResponse(
            minimum_component_pixels=(
                components["minimum_component_pixels"]
                if "minimum_component_pixels" in components
                else components["configuration"]["min_pixels"]
            ),
            connectivity=components["connectivity"],
            all_changed=_component_group(components["all_changed"]),
            road_change=_component_group(components["road_change"]),
            building_change=_component_group(components["building_change"]),
        ),
        geospatial=GeospatialResponse(
            physical_area_m2=facts.get("physical_area_m2"),
            physical_area_hectares=facts.get("physical_area_hectares"),
            coordinates=facts.get("coordinates"),
        ),
        confidence=ConfidenceResponse(
            source=payload["confidence"]["source"], note=payload["confidence"]["note"]
        ),
        artifacts=artifacts,
        timing=TimingResponse(**payload["timing"]),
        model=ModelMetadataResponse(
            name=payload["model"]["name"],
            checkpoint_sha256=payload["model"]["checkpoint_sha256"],
            device=payload["model"]["device"],
            vocab_size=468,
        ),
        warnings=list(payload["warnings"]),
    )


def create_app(
    state: WorkerState,
    *,
    image_policy: ImagePolicy = ImagePolicy.PRODUCTION_TIFF,
) -> FastAPI:
    """Create an application without initializing MCI; tests inject a fake analyzer."""
    app = FastAPI(title="SatQuery MCI Worker", docs_url=None, redoc_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error_response(422, "INVALID_REQUEST", "The request contract is invalid.")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/ready", response_model=ReadyResponse)
    def ready() -> ReadyResponse | JSONResponse:
        readiness = state.readiness()
        if isinstance(readiness, ReadyResponse):
            return readiness
        return JSONResponse(status_code=503, content=readiness.model_dump(mode="json"))

    @app.post("/v1/change-analysis", response_model=ChangeAnalysisSuccessResponse)
    def change_analysis(request: ChangeAnalysisRequest) -> ChangeAnalysisSuccessResponse | JSONResponse:
        if state.phase is not WorkerPhase.READY or state.analyzer is None:
            return _error_response(503, "MODEL_NOT_READY", "The MCI model is not ready.", request_id=request.request_id)
        try:
            before = _contained_existing_input(request.before_path, state.config.input_root)
            after = _contained_existing_input(request.after_path, state.config.input_root)
        except FileNotFoundError:
            return _error_response(422, "INPUT_FILE_NOT_FOUND", "A requested input file was not found.", request_id=request.request_id)
        except ValueError:
            return _error_response(422, "INVALID_REQUEST", "Input paths must be within the configured input root.", request_id=request.request_id)
        try:
            _validate_mci_image_pair(before, after, image_policy=image_policy)
        except UnsupportedImageError:
            return _error_response(
                422,
                "UNSUPPORTED_IMAGE",
                "Inputs must be readable 256x256 RGB images.",
                request_id=request.request_id,
            )

        if not state.slot.acquire(timeout=state.config.busy_wait_seconds):
            return _error_response(429, "WORKER_BUSY", "The worker is busy; retry shortly.", retryable=True, request_id=request.request_id)
        try:
            state.config.output_root.mkdir(parents=True, exist_ok=True)
            result = state.analyzer.analyze(
                before,
                after,
                geo_metadata=request.geo_metadata,
                output_dir=state.config.output_root,
                job_id=uuid4().hex,
            )
            return _success_response(result, request.request_id, state.config.output_root)
        except ValueError:
            LOGGER.exception("MCI worker input or artifact validation failed")
            return _error_response(500, "ARTIFACT_WRITE_FAILED", "Worker artifacts could not be prepared.", request_id=request.request_id)
        except Exception:
            LOGGER.exception("MCI inference failed")
            return _error_response(500, "INFERENCE_FAILED", "MCI inference failed.", request_id=request.request_id)
        finally:
            state.slot.release()

    return app


def initialize_production_state(config: WorkerConfig) -> WorkerState:
    """Load the frozen MCI runtime once, retaining a live HTTP process on failure."""
    state = WorkerState(config)
    try:
        # Intentionally lazy: the shared contract and fake-runtime API never import MCI/Torch.
        from .change_analysis_tool import ChangeAnalysisTool
        from .mci_inference import EXPECTED_VOCAB_SIZE, MCIInference

        runtime = MCIInference(checkpoint_path=config.checkpoint, device=config.device)
        analyzer = ChangeAnalysisTool(runtime, default_output_root=config.output_root)
        state.mark_ready(
            analyzer,
            model_name="Change-Agent MCI",
            checkpoint_sha256=analyzer.checkpoint_sha256,
            vocab_size=EXPECTED_VOCAB_SIZE,
        )
    except Exception:
        LOGGER.exception("MCI worker initialization failed")
        state.mark_failed()
    return state
