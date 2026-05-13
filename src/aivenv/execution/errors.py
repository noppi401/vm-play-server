"""Domain-specific exception hierarchy for aivenv execution."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from aivenv.execution.models import ErrorResponse


class AivenvError(Exception):
    """Base class for expected application errors."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "aivenv_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code
        if cause is not None:
            self.__cause__ = cause

    def to_response(self) -> ErrorResponse:
        """Convert this exception into a public API error payload."""
        return ErrorResponse(error=self.code, message=self.message, details=self.details)


class ConflictError(AivenvError):
    """Raised when a request conflicts with current execution state."""

    status_code = HTTPStatus.CONFLICT
    code = "conflict"


class CodeGenError(AivenvError):
    """Raised when AI code generation fails or returns invalid output."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "code_generation_failed"


class ContainerError(AivenvError):
    """Raised when container startup, execution, or cleanup fails."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "container_error"


class NgrokError(AivenvError):
    """Raised when ngrok tunnel creation or lifecycle management fails."""

    status_code = HTTPStatus.BAD_GATEWAY
    code = "ngrok_error"


class NotFoundError(AivenvError):
    """Raised when a requested execution resource does not exist."""

    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"


class ConfigError(AivenvError):
    """Raised when required configuration is missing or invalid."""

    status_code = HTTPStatus.BAD_REQUEST
    code = "config_error"
