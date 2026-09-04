from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Modality(StrEnum):
    OPTICAL = "optical"
    SAR = "sar"
    UNKNOWN = "unknown"


class ModalityHint(StrEnum):
    AUTO = "auto"
    OPTICAL = "optical"
    SAR = "sar"


class Task(StrEnum):
    SINGLE_IMAGE = "single_image"
    CHANGE = "change"
    OPTICAL_SAR = "optical_sar"
    REJECT = "reject"


class OverlayType(StrEnum):
    HEATMAP = "heatmap"
    CHANGE_MASK = "change_mask"
    NONE = "none"


class Bounds(BaseModel):
    left: float
    bottom: float
    right: float
    top: float


class ValueProvenance(BaseModel):
    source: Literal[
        "user",
        "tag",
        "band_description",
        "band_count_heuristic",
        "unknown",
    ]
    detected_value: str | None = None
    detected_source: str | None = None


class MetadataProvenance(BaseModel):
    modality: ValueProvenance
    acquisition_date: ValueProvenance


class RasterMetadata(BaseModel):
    driver: str
    width: int
    height: int
    band_count: int
    dtypes: list[str]
    crs: str
    bounds: Bounds
    transform: list[float] = Field(min_length=6, max_length=6)
    resolution: list[float] = Field(min_length=2, max_length=2)
    nodata: float | None
    band_descriptions: list[str | None]
    tags: dict[str, str]
    modality: Modality
    acquisition_date: date | None
    provenance: MetadataProvenance


class UploadResponse(BaseModel):
    asset_id: UUID
    original_name: str
    size_bytes: int
    sha256: str
    created_at: datetime
    expires_at: datetime
    metadata: RasterMetadata
    warnings: list[str]


class QueryRequest(BaseModel):
    asset_ids: list[UUID] = Field(min_length=1, max_length=2)
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class Overlay(BaseModel):
    type: OverlayType = OverlayType.NONE
    file: str | None = None


class TraceStep(BaseModel):
    stage: Literal["checker", "router", "tool"]
    status: Literal["ok", "rejected", "stub"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Receipt(BaseModel):
    why_this_tool: str
    rejected: bool
    reason: str | None
    trace: list[TraceStep]


class ResultEnvelope(BaseModel):
    task: Task
    tools: list[str]
    parameters: dict[str, Any]
    facts: dict[str, Any]
    answer_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str]
    overlay: Overlay
    receipt: Receipt


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class AssetRecord(UploadResponse):
    model_config = ConfigDict(extra="forbid")
    stored_name: str


class RoutePlan(BaseModel):
    task: Task
    tool: str | None
    ordered_asset_ids: list[UUID]
    parameters: dict[str, Any]
    why: str
    rejected: bool = False
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    overlay: Overlay = Field(default_factory=Overlay)
