"""Torch-free synchronous client for the isolated local MCI worker."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from satquery.tools.change_mci_protocol import (
    ChangeAnalysisErrorResponse,
    ChangeAnalysisRequest,
    ChangeAnalysisSuccessResponse,
    HealthResponse,
    ReadyResponse,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8012"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 1.0
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 15.0
DEFAULT_MAXIMUM_RESPONSE_BYTES = 1_048_576


@dataclass
class MCIWorkerClientError(Exception):
    """Safe client-layer failure; never stores a raw transport exception/body."""

    code: str
    message: str
    http_status: int | None = None
    retryable: bool = False
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class MCIWorkerClient:
    """Validate every local-worker response before exposing it to SatQuery."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        analysis_timeout_seconds: float = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
        maximum_response_bytes: int = DEFAULT_MAXIMUM_RESPONSE_BYTES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be blank")
        if connect_timeout_seconds <= 0 or analysis_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if maximum_response_bytes <= 0:
            raise ValueError("maximum_response_bytes must be positive")
        self.base_url = base_url.rstrip("/")
        self.connect_timeout_seconds = connect_timeout_seconds
        self.analysis_timeout_seconds = analysis_timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self._client = httpx.Client(base_url=self.base_url, transport=transport)

    def close(self) -> None:
        self._client.close()

    def health(self) -> HealthResponse:
        status, payload = self._request("GET", "/health", timeout_seconds=self.connect_timeout_seconds)
        if status != 200:
            self._raise_worker_error(status, payload)
        try:
            return HealthResponse.model_validate(payload)
        except ValidationError as error:
            raise self._invalid_response() from error

    def ready(self) -> ReadyResponse:
        status, payload = self._request("GET", "/ready", timeout_seconds=self.connect_timeout_seconds)
        if status != 200:
            self._raise_worker_error(status, payload)
        try:
            return ReadyResponse.model_validate(payload)
        except ValidationError as error:
            raise self._invalid_response() from error

    def analyze(self, request: ChangeAnalysisRequest) -> ChangeAnalysisSuccessResponse:
        status, payload = self._request(
            "POST",
            "/v1/change-analysis",
            json_body=request.model_dump(mode="json"),
            timeout_seconds=self.analysis_timeout_seconds,
        )
        if status != 200:
            self._raise_worker_error(status, payload)
        try:
            response = ChangeAnalysisSuccessResponse.model_validate(payload)
        except ValidationError as error:
            raise self._invalid_response() from error
        if response.request_id != request.request_id:
            raise self._invalid_response()
        return response

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout_seconds: float,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        timeout = httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=self.connect_timeout_seconds,
        )
        try:
            with self._client.stream(method, path, json=json_body, timeout=timeout) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.maximum_response_bytes:
                        raise self._invalid_response()
        except MCIWorkerClientError:
            raise
        except httpx.TimeoutException as error:
            raise MCIWorkerClientError("WORKER_TIMEOUT", "The MCI worker timed out.") from error
        except httpx.NetworkError as error:
            raise MCIWorkerClientError("WORKER_UNAVAILABLE", "The MCI worker is unavailable.") from error
        except httpx.HTTPError as error:
            raise MCIWorkerClientError("WORKER_TRANSPORT_ERROR", "The MCI worker request failed.") from error
        try:
            return response.status_code, json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise self._invalid_response() from error

    def _raise_worker_error(self, status: int, payload: Any) -> None:
        try:
            worker_error = ChangeAnalysisErrorResponse.model_validate(payload).error
        except ValidationError as error:
            raise self._invalid_response(http_status=status) from error
        raise MCIWorkerClientError(
            code=worker_error.code,
            message=worker_error.message,
            http_status=status,
            retryable=worker_error.retryable,
        )

    @staticmethod
    def _invalid_response(http_status: int | None = None) -> MCIWorkerClientError:
        return MCIWorkerClientError(
            "INVALID_WORKER_RESPONSE",
            "The MCI worker returned an invalid response.",
            http_status=http_status,
        )
