from __future__ import annotations

from typing import Any, Mapping
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

try:
    from aivenv.api import create_app
except ImportError:
    from aivenv.server import create_app  # type: ignore[no-redef]

try:
    from aivenv.execution.manager import ExecutionManager
except ImportError:
    from aivenv.manager import ExecutionManager  # type: ignore[no-redef]

try:
    from aivenv.errors import CodeGenError, ContainerError
except ImportError:
    from aivenv.execution.errors import CodeGenError, ContainerError  # type: ignore[no-redef]


JsonObject = Mapping[str, Any]


class MockCodeGenerator:
    def __init__(self, *, code: str = "print('hello from integration test')") -> None:
        self.openai_client: MagicMock = MagicMock(name="openai_client")
        self.generate: AsyncMock = AsyncMock(name="generate", side_effect=self._generate)
        self.code = code

    async def _generate(self, *args: Any, **kwargs: Any) -> str:
        return self.code


class MockContainerClient:
    def __init__(self) -> None:
        self.containers: MagicMock = MagicMock(name="containers")
        self.containers.run.return_value = MagicMock(id="container-test-001", port=8765, host_port=8765)


class MockContainerManager:
    def __init__(self, docker_client: MockContainerClient | None = None) -> None:
        self.docker_client: MockContainerClient = docker_client or MockContainerClient()
        self.log_server_port = 8765
        self.container = MagicMock(id="container-test-001", port=8765, host_port=8765)
        self.start: MagicMock = MagicMock(name="start", side_effect=self._start)
        self.start_container: AsyncMock = AsyncMock(name="start_container", side_effect=self._start_container)

    def _start(self, *args: Any, **kwargs: Any) -> Any:
        self.docker_client.containers.run("python:3.11-slim", detach=True)
        return self.container

    async def _start_container(self, *args: Any, **kwargs: Any) -> Any:
        self.docker_client.containers.run("python:3.11-slim", detach=True)
        return self.container


class MockNgrokManager:
    def __init__(self, result_url: str = "https://run-flow-test.ngrok.io") -> None:
        self.open_tunnel: AsyncMock = AsyncMock(name="open_tunnel", side_effect=self._open_tunnel)
        self.open: AsyncMock = AsyncMock(name="open", side_effect=self._open_tunnel)
        self.result_url = result_url

    async def _open_tunnel(self, *args: Any, **kwargs: Any) -> str:
        return self.result_url


def _build_execution_manager(
    *,
    code_generator: MockCodeGenerator,
    container_manager: MockContainerManager,
    ngrok_manager: MockNgrokManager,
) -> ExecutionManager:
    try:
        return ExecutionManager(
            code_generator=code_generator,
            container_manager=container_manager,
            ngrok_manager=ngrok_manager,
        )
    except TypeError:
        return ExecutionManager(code_generator, container_manager, ngrok_manager)


def _session(manager: ExecutionManager) -> Any:
    return getattr(manager, "current_session", None) or getattr(manager, "active_session", None) or getattr(manager, "_session", None)


def _assert_no_active_execution(manager: ExecutionManager) -> None:
    assert _session(manager) is None
    assert getattr(manager, "active_execution_id", None) is None


@pytest.fixture()
def code_generator() -> MockCodeGenerator:
    return MockCodeGenerator()


@pytest.fixture()
def docker_client() -> MockContainerClient:
    return MockContainerClient()


@pytest.fixture()
def container_manager(docker_client: MockContainerClient) -> MockContainerManager:
    return MockContainerManager(docker_client=docker_client)


@pytest.fixture()
def ngrok_manager() -> MockNgrokManager:
    return MockNgrokManager()


@pytest.fixture()
def execution_manager(
    code_generator: MockCodeGenerator,
    container_manager: MockContainerManager,
    ngrok_manager: MockNgrokManager,
) -> ExecutionManager:
    return _build_execution_manager(
        code_generator=code_generator,
        container_manager=container_manager,
        ngrok_manager=ngrok_manager,
    )


@pytest.fixture()
def client(execution_manager: ExecutionManager) -> TestClient:
    return TestClient(create_app(execution_manager=execution_manager))


def _json(response: Any) -> JsonObject:
    body = response.json()
    assert isinstance(body, Mapping)
    return body


def _message(body: JsonObject) -> str:
    value = body.get("message", body.get("detail", body.get("error", "")))
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _assert_container_started(container_manager: MockContainerManager, docker_client: MockContainerClient) -> None:
    assert container_manager.start.called or container_manager.start_container.await_count == 1
    docker_client.containers.run.assert_called_once()


def test_post_run_returns_202_with_execution_id_and_result_url(
    client: TestClient,
    code_generator: MockCodeGenerator,
    container_manager: MockContainerManager,
    docker_client: MockContainerClient,
    ngrok_manager: MockNgrokManager,
) -> None:
    response = client.post("/run", json={"instruction": "Create a small Python hello-world script."})

    assert response.status_code == 202
    body = _json(response)
    assert isinstance(body["execution_id"], str)
    assert body["execution_id"]
    assert body["result_url"] == "https://run-flow-test.ngrok.io"
    code_generator.generate.assert_awaited_once()
    _assert_container_started(container_manager, docker_client)
    assert ngrok_manager.open_tunnel.await_count + ngrok_manager.open.await_count == 1


@pytest.mark.parametrize("payload", [{}, {"instruction": ""}, {"instruction": "   "}])
def test_post_run_returns_400_on_empty_instruction(
    client: TestClient,
    code_generator: MockCodeGenerator,
    container_manager: MockContainerManager,
    payload: dict[str, str],
) -> None:
    response = client.post("/run", json=payload)

    assert response.status_code == 400
    assert "instruction" in _message(_json(response)).lower()
    code_generator.generate.assert_not_awaited()
    container_manager.start.assert_not_called()
    container_manager.start_container.assert_not_awaited()


def test_post_run_returns_409_on_concurrent_run_attempt(
    client: TestClient,
    code_generator: MockCodeGenerator,
    container_manager: MockContainerManager,
) -> None:
    first_response = client.post("/run", json={"instruction": "Run the first task."})
    assert first_response.status_code == 202

    response = client.post("/run", json={"instruction": "Run another task."})

    assert response.status_code == 409
    assert ("active" in _message(_json(response)).lower()) or ("already" in _message(_json(response)).lower()) or ("running" in _message(_json(response)).lower())
    code_generator.generate.assert_awaited_once()
    assert container_manager.start.call_count + container_manager.start_container.await_count == 1


def test_post_run_returns_500_on_codegen_error(
    client: TestClient,
    execution_manager: ExecutionManager,
    code_generator: MockCodeGenerator,
    container_manager: MockContainerManager,
) -> None:
    code_generator.generate.side_effect = CodeGenError("OpenAI code generation failed")

    response = client.post("/run", json={"instruction": "Generate code that fails."})

    assert response.status_code == 500
    assert ("generation" in _message(_json(response)).lower()) or ("openai" in _message(_json(response)).lower())
    code_generator.generate.assert_awaited_once()
    container_manager.start.assert_not_called()
    container_manager.start_container.assert_not_awaited()
    _assert_no_active_execution(execution_manager)


def test_post_run_returns_500_on_container_error(
    client: TestClient,
    execution_manager: ExecutionManager,
    code_generator: MockCodeGenerator,
    container_manager: MockContainerManager,
) -> None:
    container_error = ContainerError("Docker container failed to start")
    container_manager.start.side_effect = container_error
    container_manager.start_container.side_effect = container_error

    response = client.post("/run", json={"instruction": "Generate code but fail Docker."})

    assert response.status_code == 500
    assert ("container" in _message(_json(response)).lower()) or ("docker" in _message(_json(response)).lower())
    code_generator.generate.assert_awaited_once()
    assert container_manager.start.called or container_manager.start_container.await_count == 1
    _assert_no_active_execution(execution_manager)
