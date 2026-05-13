"""Application-specific error taxonomy for aivenv."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class AivenvError(Exception):
    """Base class for expected aivenv errors."""

    error_code = "aivenv_error"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_response(self) -> dict[str, Any]:
        """Return an ErrorResponse-compatible payload."""
        payload: dict[str, Any] = {"error": self.error_code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class ConflictError(AivenvError):
    """Raised when a request conflicts with current state."""

    error_code = "conflict"
    status_code = HTTPStatus.CONFLICT


class CodeGenError(AivenvError):
    """Raised when AI code generation fails."""

    error_code = "code_generation_failed"


class ContainerError(AivenvError):
    """Raised for container runtime failures."""

    error_code = "container_error"


class NgrokError(AivenvError):
    """Raised when ngrok tunnel setup fails."""

    error_code = "ngrok_error"


class NotFoundError(AivenvError):
    """Raised when a requested resource does not exist."""

    error_code = "not_found"
    status_code = HTTPStatus.NOT_FOUND


class ConfigError(AivenvError):
    """Raised when configuration is missing or invalid."""

    error_code = "configuration_error"
    status_code = HTTPStatus.BAD_REQUEST
