"""Tests for execution models and errors."""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

import pytest
from pydantic import ValidationError

from aivenv.execution.errors import (
    AivenvError,
    CodeGenError,
    ConfigError,
    ConflictError,
    ContainerError,
    NgrokError,
    NotFoundError,
)
from aivenv.execution.models import (
    ErrorResponse,
    ExecutionSession,
    ExecutionStatus,
    RunRequest,
    RunResponse,
    StopResponse,
)


def test_run_request_strips_and_requires_instruction() -> None:
    request = RunRequest(instruction="  build a fastapi app  ")

    assert request.instruction == "build a fastapi app"

    with pytest.raises(ValidationError):
        RunRequest(instruction="   ")


def test_execution_session_defaults_and_status_update() -> None:
    session = ExecutionSession(instruction="print hello")

    assert isinstance(session.execution_id, UUID)
    assert session.status is ExecutionStatus.PENDING
    assert session.error_message is None

    original_updated_at = session.updated_at
    session.mark_status(ExecutionStatus.FAILED, error_message="container failed")

    assert session.status is ExecutionStatus.FAILED
    assert session.error_message == "container failed"
    assert session.updated_at >= original_updated_at


def test_response_models_validate() -> None:
    execution_id = "1f941145-f4a4-4f07-9a40-7ce4cd321783"

    run = RunResponse(execution_id=execution_id, result_url="https://example.ngrok.io")
    stop = StopResponse(execution_id=execution_id)
    error = ErrorResponse(error="conflict", message="already active")

    assert run.execution_id == UUID(execution_id)
    assert str(run.result_url) == "https://example.ngrok.io/"
    assert stop.status is ExecutionStatus.STOPPED
    assert error.details is None


def test_error_taxonomy_responses() -> None:
    cases = [
        (ConflictError("active"), "conflict", HTTPStatus.CONFLICT),
        (CodeGenError("bad output"), "code_generation_failed", HTTPStatus.INTERNAL_SERVER_ERROR),
        (ContainerError("docker failed"), "container_error", HTTPStatus.INTERNAL_SERVER_ERROR),
        (NgrokError("no url"), "ngrok_error", HTTPStatus.INTERNAL_SERVER_ERROR),
        (NotFoundError("missing"), "not_found", HTTPStatus.NOT_FOUND),
        (ConfigError("missing token"), "configuration_error", HTTPStatus.BAD_REQUEST),
    ]

    for error, code, status in cases:
        assert isinstance(error, AivenvError)
        assert error.error_code == code
        assert error.status_code == status
        assert error.to_response() == {"error": code, "message": error.message}


def test_error_details_are_optional() -> None:
    error = ContainerError("failed", details={"container_id": "abc123"})

    assert error.to_response() == {
        "error": "container_error",
        "message": "failed",
        "details": {"container_id": "abc123"},
    }
