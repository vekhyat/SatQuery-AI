from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from satquery import __version__
from satquery.checker import CHECKER_VERSION
from satquery.contracts import (
    ErrorDetail,
    ErrorEnvelope,
    ModalityHint,
    QueryRequest,
    ResultEnvelope,
    Task,
    UploadResponse,
)
from satquery.errors import SatQueryError
from satquery.registry import build_tool_registry
from satquery.router import ROUTER_VERSION
from satquery.service import SatQueryService
from satquery.storage import AssetStore
from satquery.tools.mci_worker_client import (
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_BASE_URL,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    MCIWorkerClient,
)
from satquery.tools.change_mci_artifacts import artifact_path as tool2_artifact_path
from satquery.tools.change_mci_artifacts import media_type as tool2_artifact_media_type
from satquery.tools.optical_sar import artifact_path
from satquery.tools.single_image import artifact_path as tool1_artifact_path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    runtime_dir: Path
    max_upload_bytes: int = 100 * 1024 * 1024
    retention_hours: int = 24
    mci_worker_url: str = DEFAULT_BASE_URL
    mci_connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    mci_analysis_timeout_seconds: float = DEFAULT_ANALYSIS_TIMEOUT_SECONDS
    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    @classmethod
    def from_environment(cls) -> "Settings":
        origins = os.getenv("SATQUERY_CORS_ORIGINS")
        return cls(
            runtime_dir=Path(
                os.getenv("SATQUERY_RUNTIME_DIR", REPOSITORY_ROOT / "runtime" / "uploads")
            ),
            max_upload_bytes=int(
                os.getenv("SATQUERY_MAX_UPLOAD_MIB", "100")
            )
            * 1024
            * 1024,
            retention_hours=int(os.getenv("SATQUERY_RETENTION_HOURS", "24")),
            mci_worker_url=os.getenv("SATQUERY_MCI_WORKER_URL", DEFAULT_BASE_URL),
            mci_connect_timeout_seconds=float(
                os.getenv(
                    "SATQUERY_MCI_CONNECT_TIMEOUT_SECONDS",
                    str(DEFAULT_CONNECT_TIMEOUT_SECONDS),
                )
            ),
            mci_analysis_timeout_seconds=float(
                os.getenv(
                    "SATQUERY_MCI_ANALYSIS_TIMEOUT_SECONDS",
                    str(DEFAULT_ANALYSIS_TIMEOUT_SECONDS),
                )
            ),
            cors_origins=(
                tuple(value.strip() for value in origins.split(",") if value.strip())
                if origins
                else cls.__dataclass_fields__["cors_origins"].default
            ),
        )


def _error_response(
    status_code: int, code: str, message: str, details: dict | None = None
) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, details=details or {})
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def create_app(
    settings: Settings | None = None,
    *,
    mci_client: MCIWorkerClient | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_environment()
    store = AssetStore(
        active_settings.runtime_dir,
        max_upload_bytes=active_settings.max_upload_bytes,
        retention=timedelta(hours=active_settings.retention_hours),
    )
    owns_mci_client = mci_client is None
    active_mci_client = mci_client or MCIWorkerClient(
        base_url=active_settings.mci_worker_url,
        connect_timeout_seconds=active_settings.mci_connect_timeout_seconds,
        analysis_timeout_seconds=active_settings.mci_analysis_timeout_seconds,
    )
    service = SatQueryService(
        store,
        tool_registry=build_tool_registry(active_mci_client),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.cleanup_expired()
        try:
            yield
        finally:
            if owns_mci_client:
                active_mci_client.close()

    app = FastAPI(
        title="SatQuery AI API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.store = store
    app.state.service = service
    app.state.mci_client = active_mci_client
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(SatQueryError)
    async def satquery_error_handler(_request: Request, exc: SatQueryError):
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        safe_errors = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            422,
            "request_validation_error",
            "The request did not match the API contract.",
            {"errors": safe_errors},
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "checker": CHECKER_VERSION,
            "router": ROUTER_VERSION,
        }

    @app.post(
        "/upload",
        response_model=UploadResponse,
        status_code=status.HTTP_201_CREATED,
        responses={413: {"model": ErrorEnvelope}, 415: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
    )
    async def upload(
        file: UploadFile = File(...),
        modality: ModalityHint = Form(ModalityHint.AUTO),
        acquisition_date: date | None = Form(None),
    ) -> UploadResponse:
        try:
            return await service.upload(file, modality, acquisition_date)
        finally:
            await file.close()

    @app.post(
        "/query",
        response_model=ResultEnvelope,
        responses={404: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
    )
    def query(payload: QueryRequest, request: Request) -> ResultEnvelope:
        artifact_root = request.scope.get("root_path", "").rstrip("/") + "/artifacts"
        return service.query(payload.asset_ids, payload.question, artifact_root_url=artifact_root)

    @app.get("/artifacts/tool3/{run_id}/{filename}")
    def tool3_artifact(run_id: str, filename: str) -> FileResponse:
        path = artifact_path(service.tool_context(), run_id, filename)
        return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/tiff",
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/artifacts/tool2/{run_id}/{filename}")
    def tool2_artifact(run_id: str, filename: str) -> FileResponse:
        context = service.tool_context(Task.CHANGE)
        path = tool2_artifact_path(context, run_id, filename)
        return FileResponse(
            path,
            media_type=tool2_artifact_media_type(filename),
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/artifacts/tool1/{run_id}/{filename}")
    def tool1_artifact(run_id: str, filename: str) -> FileResponse:
        context = service.tool_context(Task.SINGLE_IMAGE)
        path = tool1_artifact_path(context, run_id, filename)
        return FileResponse(
            path,
            media_type="image/png" if path.suffix == ".png" else "application/json",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return app


app = create_app()
