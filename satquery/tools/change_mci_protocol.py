"""Versioned, Torch-free HTTP contract for the isolated Tool 2 MCI worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONTRACT_VERSION = "1.0"
WORKER_SERVICE_NAME = "satquery-mci-worker"


class ProtocolModel(BaseModel):
    """Reject accidental fields so worker and future client drift is visible."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WorkerError(ProtocolModel):
    code: Literal[
        "MODEL_NOT_READY",
        "WORKER_BUSY",
        "INVALID_REQUEST",
        "INPUT_FILE_NOT_FOUND",
        "UNSUPPORTED_IMAGE",
        "INFERENCE_FAILED",
        "ARTIFACT_WRITE_FAILED",
    ]
    message: str = Field(min_length=1, max_length=240)
    retryable: bool = False


class HealthResponse(ProtocolModel):
    status: Literal["ok"] = "ok"
    service: Literal[WORKER_SERVICE_NAME] = WORKER_SERVICE_NAME
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION


class ReadyResponse(ProtocolModel):
    status: Literal["ready"] = "ready"
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    model: str = Field(min_length=1, max_length=120)
    device: str = Field(min_length=1, max_length=80)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vocab_size: Literal[468] = 468


class NotReadyResponse(ProtocolModel):
    status: Literal["not_ready"] = "not_ready"
    error: WorkerError


class ChangeAnalysisRequest(ProtocolModel):
    contract_version: Literal[CONTRACT_VERSION]
    request_id: UUID
    before_path: str = Field(min_length=1, max_length=4096)
    after_path: str = Field(min_length=1, max_length=4096)
    geo_metadata: dict[str, Any] | None = None

    @field_validator("before_path", "after_path")
    @classmethod
    def absolute_server_path_required(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("must be an absolute server-owned path")
        return value


class CaptionResponse(ProtocolModel):
    text: str = Field(min_length=1, max_length=4000)
    source: str = Field(min_length=1, max_length=240)
    question_conditioned: Literal[False] = False


class ClassStatisticsResponse(ProtocolModel):
    class_id: Literal[0, 1, 2]
    label: str = Field(min_length=1, max_length=80)
    pixel_count: int = Field(ge=0)
    percent_of_valid_pixels: float = Field(ge=0, le=100)
    percent_of_changed_pixels: float | None = Field(default=None, ge=0, le=100)


class StatisticsResponse(ProtocolModel):
    total_pixels: int = Field(ge=0)
    valid_pixels: int = Field(ge=0)
    unchanged_pixels: int = Field(ge=0)
    changed_pixels: int = Field(ge=0)
    changed_fraction: float = Field(ge=0, le=1)
    changed_percent: float = Field(ge=0, le=100)
    per_class: dict[str, ClassStatisticsResponse]

    @model_validator(mode="after")
    def counts_must_describe_the_valid_pixels(self) -> "StatisticsResponse":
        if self.valid_pixels > self.total_pixels:
            raise ValueError("valid_pixels cannot exceed total_pixels")
        if self.changed_pixels > self.valid_pixels:
            raise ValueError("changed_pixels cannot exceed valid_pixels")
        if self.unchanged_pixels + self.changed_pixels != self.valid_pixels:
            raise ValueError("changed and unchanged pixels must equal valid_pixels")
        return self


class ComponentItemResponse(ProtocolModel):
    component_id: int = Field(ge=1)
    class_name: str = Field(min_length=1, max_length=80)
    class_id: Literal[1, 2] | None = None
    pixel_area: int = Field(ge=1)
    bounding_box_pixels: dict[str, int]
    centroid_pixels: dict[str, float]
    percent_of_total_changed_pixels: float = Field(ge=0, le=100)


class ComponentGroupResponse(ProtocolModel):
    raw_component_count: int = Field(ge=0)
    filtered_component_count: int = Field(ge=0)
    filtered_pixel_count: int = Field(ge=0)
    largest_component_pixels: int | None = Field(default=None, ge=1)
    top_components: list[ComponentItemResponse] = Field(default_factory=list, max_length=10)


class ComponentsResponse(ProtocolModel):
    minimum_component_pixels: int = Field(ge=1)
    connectivity: Literal[4, 8]
    all_changed: ComponentGroupResponse
    road_change: ComponentGroupResponse
    building_change: ComponentGroupResponse


class GeospatialResponse(ProtocolModel):
    physical_area_m2: float | None = Field(default=None, ge=0)
    physical_area_hectares: float | None = Field(default=None, ge=0)
    coordinates: dict[str, Any] | None = None


class ConfidenceResponse(ProtocolModel):
    status: Literal["not_measured"] = "not_measured"
    source: str = Field(min_length=1, max_length=240)
    note: str = Field(min_length=1, max_length=1000)


class ArtifactFilenames(ProtocolModel):
    semantic_mask: str
    semantic_mask_rgb: str
    binary_mask: str
    overlay: str
    components: str

    @field_validator("*")
    @classmethod
    def filenames_must_not_contain_paths(cls, value: str) -> str:
        if (
            not value
            or Path(value).name != value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("artifact fields must be filenames only")
        return value


class TimingResponse(ProtocolModel):
    inference_seconds: float = Field(ge=0)
    postprocessing_seconds: float = Field(ge=0)
    total_seconds: float = Field(ge=0)


class ModelMetadataResponse(ProtocolModel):
    name: str = Field(min_length=1, max_length=120)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    device: str = Field(min_length=1, max_length=80)
    vocab_size: Literal[468] = 468


class ChangeAnalysisSuccessResponse(ProtocolModel):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    request_id: UUID
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    caption: CaptionResponse
    statistics: StatisticsResponse
    components: ComponentsResponse
    geospatial: GeospatialResponse
    confidence: ConfidenceResponse
    artifacts: ArtifactFilenames
    timing: TimingResponse
    model: ModelMetadataResponse
    warnings: list[str] = Field(default_factory=list, max_length=50)


class ChangeAnalysisErrorResponse(ProtocolModel):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    request_id: UUID | None = None
    error: WorkerError
