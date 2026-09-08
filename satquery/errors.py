from __future__ import annotations

from typing import Any


class SatQueryError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class ToolExecutionError(SatQueryError):
    """Safe, task-neutral specialist failure consumed by orchestration."""

    def __init__(
        self,
        http_status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        as_rejection: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(http_status, code, message, details)
        self.http_status = http_status
        self.retryable = retryable
        self.as_rejection = as_rejection
