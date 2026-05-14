"""FastAPI HTTP API for aivenv executions."""

from __future__ import annotations

import inspect
import logging
from http import HTTPStatus
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from aivenv.config import Settings, load_settings
from aivenv.execution.code_generator import CodeGenerator
from aivenv.execution.container import ContainerManager
from aivenv.execution.errors import AivenvError, ConfigError
from aivenv.execution.manager import ExecutionManager
from aivenv.execution.models import ErrorResponse, ExecutionStatus, RunRequest, RunResponse, StopResponse
from aivenv.log_server import PORT as LOG_PORT, get_log_buffer, set_execution_metadata

LOCALHOST = "127.0.0.1"
PORT = 8080

logger = logging.getLogger(__name__)
_manager: ExecutionManager | None = None


def _error_response(
    status_code: int,
    error: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=error, message=message, details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def _map_execution_error(exc: BaseException) -> JSONResponse:
    if isinstance(exc, AivenvError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_response().model_dump(exclude_none=True))

    name = exc.__class__.__name__
    if name == "ConflictError":
        return _error_response(HTTPStatus.CONFLICT, "conflict", str(exc))
    if name == "NotFoundError":
        return _error_response(HTTPStatus.NOT_FOUND, "not_found", str(exc))

    return _error_response(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_server_error", str(exc))


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
    return ExecutionManager(
        code_generator,
        container_manager,
        ngrok_manager=None,
        cleanup_on_stop=settings.cleanup_on_exit,
        log_buffer_factory=get_log_buffer,
        metadata_store=set_execution_metadata,
    )


def _session_id(session: Any) -> str:
    session_id = (
        getattr(session, "execution_id", None)
        or getattr(session, "session_id", None)
        or getattr(session, "id", None)
    )
    return str(session_id) if session_id is not None else f"unknown-{uuid4().hex}"


def _session_url(session: Any) -> str | None:
    url = getattr(session, "result_url", None) or getattr(session, "public_url", None) or getattr(session, "url", None)
    return str(url) if url is not None else None


def get_execution_manager() -> ExecutionManager:
    global _manager
    if _manager is None:
        _manager = create_execution_manager()
    return _manager


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        "bad_request",
        "Request validation failed.",
        {"errors": jsonable_encoder(exc.errors())},
    )


def create_app(execution_manager: ExecutionManager | None = None) -> FastAPI:
    if not isinstance(execution_manager, ExecutionManager):
        execution_manager = None
    app = FastAPI(title="aivenv API")
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    def manager_dependency() -> ExecutionManager:
        return execution_manager or get_execution_manager()

    @app.post("/run", response_model=RunResponse, status_code=HTTPStatus.ACCEPTED)
    async def run(
        request: RunRequest,
        manager: ExecutionManager = Depends(manager_dependency),
    ) -> RunResponse | JSONResponse:
        try:
            session = await _maybe_await(manager.start_run(request.instruction))
        except ValueError as exc:
            return _error_response(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
        except BaseException as exc:  # noqa: BLE001
            logger.exception("failed to start execution")
            return _map_execution_error(exc)

        eid = _session_id(session)
        public_url = _session_url(session)
        result_url = f"{public_url.rstrip('/')}/?id={eid}" if public_url else None
        log_url = result_url or f"http://{LOCALHOST}:{LOG_PORT}/?id={eid}"
        logger.info("Log viewer: %s", log_url)
        return RunResponse(
            execution_id=eid,
            result_url=result_url,
            status=ExecutionStatus.RUNNING,
        )

    @app.post("/stop", response_model=StopResponse, status_code=HTTPStatus.OK)
    async def stop(
        request: Request,
        manager: ExecutionManager = Depends(manager_dependency),
    ) -> StopResponse | JSONResponse:
        current_session = getattr(manager, "current_session", None)
        execution_id = _session_id(current_session) if current_session is not None else None

        requested_id: str | None = None
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("execution_id") is not None:
                requested_id = str(body["execution_id"])
        except Exception:
            requested_id = None

        try:
            await _maybe_await(manager.stop_run(session_id=requested_id))
        except BaseException as exc:  # noqa: BLE001
            logger.exception("failed to stop execution")
            return _map_execution_error(exc)

        return StopResponse(
            execution_id=execution_id,
            status=ExecutionStatus.STOPPED,
            message="Execution stopped.",
        )

    @app.get("/current")
    async def current(
        manager: ExecutionManager = Depends(manager_dependency),
    ) -> JSONResponse:
        current_session = getattr(manager, "current_session", None)
        if current_session is None:
            return JSONResponse({"active": False})
        eid = _session_id(current_session)
        public_url = _session_url(current_session)
        result_url = f"{public_url.rstrip('/')}/?id={eid}" if public_url else None
        return JSONResponse({"active": True, "execution_id": eid, "result_url": result_url})

    return app


app = create_app()


def main() -> None:
    settings = load_settings({"host": LOCALHOST, "port": PORT})
    uvicorn.run(app, host=LOCALHOST, port=settings.port)


if __name__ == "__main__":
    main()
