"""Unit tests for execution models and error taxonomy."""

from __future__ import annotations

from http import HTTPStatus

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


def test_run_request_strips_and_validates_instruction() -> None:
    request = RunRequest(instruction="  build a dashboard  ")

    assert request.instruction == "build a dashboard"



@pytest.mark.parametrize("instruction", ["", "   ", "\t\n"])
def test_run_request_rejects_empty_instruction(instruction: str) -> None:
    with pytest.raises(ValidationError):
        RunRequest(instruction=instruction)


def test_execution_session_defaults_and_terminal_status_update() -> None:
    session = ExecutionSession(execution_id="exec-1", instruction="print hello")

    assert session.status is ExecutionStatus.PENDING
    assert session.completed_at is None

    session.mark_status(ExecutionStatus.FAILED, error_message="container failed")

    assert session.status is ExecutionStatus.FAILED
    assert session.error_message == "container failed"
    assert session.completed_at == session.updated_at


def test_response_models_serialize_expected_fields() -> None:
    run_response = RunResponse(execution_id="exec-1", result_url="https://example.ngrok.io")
    stop_response = StopResponse(
        execution_id="exec-1",
        status=ExecutionStatus.STOPPED,
        message="execution stopped",
    )
    error_response = ErrorResponse(error="config_error", message="missing token")

    assert run_response.model_dump(mode="json") == {
        "execution_id": "exec-1",
        "result_url": "https://example.ngrok.io",
        "status": "running",
    }
    assert stop_response.model_dump(mode="json")["status"] == "stopped"
    assert error_response.model_dump(mode="json")["details"] is None


@pytest.mark.parametrize(
    ("error_type", "status_code", "code"),
    [
        (AivenvError, HTTPStatus.INTERNAL_SERVER_ERROR, "aivenv_error"),
        (ConflictError, HTTPStatus.CONFLICT, "conflict"),
        (CodeGenError, HTTPStatus.INTERNAL_SERVER_ERROR, "code_generation_failed"),
        (ContainerError, HTTPStatus.INTERNAL_SERVER_ERROR,"container_error"),
        (NgrokError, HTTPStatus.BAD_GATEWAY, "ngrok_error"),
        (NotFoundError, HTTPStatus.NOT_FOUND, "not_found"),
        (ConfigError, HTTPStatus.BAD_REQUEST, "config_error"),
    ],
)
def test_error_hierarchy_maps_to_error_response(
    error_type: type[AivenvError],
    status_code: HTTPStatus,
    code: str,
) 
--> None:
    error = error_type("something failed", details={"field": "value"})

    assert isinstance(error, AivenvError)
    assert error.status_code == status_code
    assert error.code == code
    assert error.to_response() == ErrorResponse(
        error=code,
        message="something failed",
        details={"field": "value"},
    )
