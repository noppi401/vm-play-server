"""FastAPI HTTP API for aivenv executions."""

from __future__ import annotations

import inspect
import logging
from http import HTTPStatus
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from aivenv.config import Settings, load_settings
from aivenv.execution.code_generator import CodeGenerator
from aivenv.execution.container import ContainerManager
from aivenv.tunnel.ngrok_manager import NgrokManager
from aivenv.execution.errors import AivenvError, ConfigError, ConflictError, NotFoundError
from aivenv.execution.manager import ExecutionManager
from aivenv.execution.models import ErrorResponse, ExecutionStatus, RunRequest, RunResponse, StopResponse
LOCALHOST = "127.0.0.1"
PORT = 8080
RUN_START_RESPONSE_TIMEOUT_SECONDS = 1.9

logger = logging.getLogger(__name__)
app = FastAPI(title="aivenv API")
_manager: ExecutionManager | None = None


def _error_response(status_code: int, error: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    body = ErrorResponse(error=error, message=message, details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        "bad_request",
        "Request validation failed.",
        {"errors": exc.errors()},
    )


def _map_execution_error(exc: AivenvError, *, default_status: int = HTTPStatus.INTERNAL_SERVER_ERROR) -> JSONResponse:
    if isinstance(exc, ConfigError):
        status_code = HTTPStatus.BAD_REQUEST
    elif isinstance(exc, ConflictError):
        status_code = HTTPStatus.CONFLICT
    elif isinstance(exc, NotFoundError):
        status_code = HTTPStatus.NOT_FOUND
    else:
        status_code = default_status

    payload = exc.to_response()
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True))


def create_execution_manager(settings: Settings | None = None) -> ExecutionManager:
    settings = settings or load_settings()
    if settings.host != LOCALHOST:
        raise ConfigError("HTTP API server must bind to 127.0.0.1.")

    code_generator = CodeGenerator(
        api_key=settings.openai_api_key_value,
        model=settings.openai_model,
    )
    container_manager = ContainerManager(
        image=settings.container_image,
        cpu_limit=settings.cpu_limit,
        memory_limit=settings.memory_limit,
    )
    ngrok_manager = NgrokManager(
        log_server_port=settings.log_port,
        auth_token=settings.ngrok_authtoken_value,
    )
    return ExecutionManager(
        code_generator,
        container_manager,
        ngrok_manager,
        cleanup_on_stop=settings.cleanup_on_exit,
    )


        return await value
    return value

def _session_id(session: Any) -> str:
    session_id = (
        getattr(session, "execution_id", None)
        or getattr(session, "session_id", None)
        or getattr(session, "id", None)
    )
    if session_id is None:
        raise ValueError("Execution session did not provide an id.")
    return str(session_id)

def _session_url(session: Any) -> str | None:
    url = (
        getattr(session, "public_url", None)
        session = await _maybe_await(manager.start_run(request.instruction))
    try:
        start_task = asyncio.create_task(_maybe_await(manager.start_run(request.instruction)))
        session = await asyncio.wait_for(
            asyncio.shield(start_task),
            timeout=RUN_START_RESPONSE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        start_task.add_done_callback(_log_background_start_error)
        current_session = getattr(manager, "current_session", None)
        return RunResponse(
            execution_id=_session_id(current_session) if current_session is not None else f"pending-{uuid4().hex}",
            result_url=_session_url(current_session) if current_session is not None else None,
            status=ExecutionStatus.RUNNING,
        )
    except AivenvError as exc:
        return _map_execution_error(exc)
    except ValueError as exc:
        return _error_response(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))

@app.post("/stop", response_model=StopResponse, status_code=HTTPStatus.OK)
async def stop(manager: ExecutionManager = Depends(get_execution_manager)) -> StopResponse | JSONResponse:
        logger.exception("failed to start execution")
        return _error_response(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_server_error", "Failed to start execution.")

    return RunResponse(
        execution_id=_session_id(session),
        result_url=_session_url(session),
        status=ExecutionStatus.RUNNING,
    except Exception:  # noqa: BLE001
    current_session = getattr(manager, "current_session", None)
    execution_id = _session_id(current_session) if current_session is not None else None

    try:
        await _maybe_await(manager.stop_run())
    except AivenvError as exc:
        return _map_execution_error(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to stop execution")
        return _error_response(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_server_error", "Failed to stop execution.")

    return StopResponse(
        execution_id=execution_id,
        status=ExecutionStatus.STOPPED,
        message="Execution stopped.",
    )


def main() -> None:
    settings = load_settings({"host": LOCALHOST, "port": PORT})
    uvicorn.run(app, host=LOCALHOST, port=settings.port)


if __name__ == "__main__":
    main()