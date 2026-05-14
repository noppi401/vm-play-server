from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

try:
    from aivenv.api import create_app
except ImportError:
    from aivenv.server import create_app  # type: ignore[no-redef]

try:
    from aivenv.errors import CodeGenError, ContainerError
except ImportError:
    from aivenv.codegen import CodeGenError  # type: ignore[no-redef]
    from aivenv.container import ContainerError  # type: ignore[no-redef]


JsonObject = Mapping[str, Any]


@dataclass(slots=True)
class RunResult:
    execution_id: str
    result_url: str


class MockCodeGenerator:
    def __init__(self, *, code: str = "print('hello from integration test')") -> None:
        self.openai_client: MagicMock = MagicMock(name="openai_client")
        self.generate: AsyncMock = AsyncMock(name="generate", return_value=code)


class MockContainerClient:
    def __init__(self) -> None:
        self.containers: MagicMock = MagicMock(name="containers")
        self.containers.run.return_value = MagicMock(id="container-test-001")


class MockContainerManager:
    def __init__(self, docker_client: MockContainerClient | None = None) -> None:
        self.docker_client: MockContainerClient = docker_client or MockContainerClient()
        self.start_container: AsyncMock = AsyncMock(side_effect=self._start_container)

    async def _start_container(self, *, execution_id: str, code: str) -> str:
        self.docker_client.containers.run("python:3.11-slim", detach=True)
        return "container-test-001"


class MockNgrokManager:
    def __init__(self, result_url: str = "https://run-flow-test.ngrok.io") -> None:
        self.open_tunnel: AsyncMock = AsyncMock(return_value=result_url)


class TestExecutionManager:
    def __init__(self, *, code_generator: MockCodeGenerator, container_manager: MockContainerManager, ngrok_manager: MockNgrokManager) -> None:
        self.code_generator = code_generator
        self.container_manager = container_manager
        self.ngrok_manager = ngrok_manager
        self.active_execution_id: str | None = None
        self._next_execution_id = "exec-run-flow-001"

    async def start_run(self, instruction: str) -> RunResult:
        if self.active_execution_id is not None:
            raise RuntimeError("execution already active")
        execution_id = self._next_execution_id
        self.active_execution_id = execution_id
        try:
            code = await self.code_generator.generate(instruction=instruction, execution_id=execution_id)
            await self.container_manager.start_container(execution_id=execution_id, code=code)
            result_url = await self.ngrok_manager.open_tunnel(execution_id=execution_id)
            return RunResult(execution_id=execution_id, result_url=result_url)
        except Exception:
            self.active_execution_id = None
            raise


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
def execution_manager(code_generator: MockCodeGenerator, container_manager: MockContainerManager, ngrok_manager: MockNgrokManager) -> TestExecutionManager:
    return TestExecutionManager(code_generator=code_generator, container_manager=container_manager, ngrok_manager=ngrok_manager)


@pytest.fixture()
def client(execution_manager: TestExecutionManager) -> TestClient:
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


def test_post_run_returns_202_with_execution_id_and_result_url(client: TestClient, code_generator: MockCodeGenerator, container_manager: MockContainerManager, docker_client: MockContainerClient, ngrok_manager: MockNgrokManager) -> None:
    response = client.post("/run", json={"instruction": "Create a small Python hello-world script."})
    assert response.status_code == 202
    body = _json(response)
    assert body["execution_id"] == "exec-run-flow-001"
    assert body["result_url"] == "https://run-flow-test.ngrok.io"
    code_generator.generate.assert_awaited_once()
    container_manager.start_container.assert_awaited_once()
    ngrok_manager.open_tunnel.assert_awaited_once()
    docker_client.containers.run.assert_called_once()


@pytest.mark.parametrize("payload", [{}, {"instruction": ""}, {"instruction": "   \t\n  "}])
def test_post_run_returns_400_on_empty_instruction(client: TestClient, code_generator: MockCodeGenerator, container_manager: MockContainerManager, payload: dict[str, str]) -> None:
    response = client.post("/run", json=payload)
    assert response.status_code == 400
    assert "instruction" in _message(_json(response)).lower()
    code_generator.generate.assert_not_awaited()
    container_manager.start_container.assert_not_awaited()


def test_post_run_returns_409_on_concurrent_run_attempt(client: TestClient, execution_manager: TestExecutionManager, code_generator: MockCodeGenerator, container_manager: MockContainerManager) -> None:
    execution_manager.active_execution_id = "exec-active-001"
    response = client.post("/run", json={"instruction": "Run another task."})
    assert response.status_code == 409
    assert ("active" in _message(_json(response)).lower()) or ("already" in _message(_json(response)).lower())
    code_generator.generate.assert_not_awaited()
    container_manager.start_container.assert_not_awaited()


def test_post_run_returns_500_on_codegen_error(client: TestClient, execution_manager: TestExecutionManager, code_generator: MockCodeGenerator, container_manager: MockContainerManager) -> None:
    code_generator.generate.side_effect = CodeGenError("OpenAI code generation failed")
    response = client.post("/run", json={"instruction": "Generate code that fails."})
    assert response.status_code == 500
    assert ("generation" in _message(_json(response)).lower()) or ("openai" in _message(_json(response)).lower())
    code_generator.generate.assert_awaited_once()
    container_manager.start_container.assert_not_awaited()
    assert execution_manager.active_execution_id is None


def test_post_run_returns_500_on_container_error(client: TestClient, execution_manager: TestExecutionManager, code_generator: MockCodeGenerator, container_manager: MockContainerManager) -> None:
    container_manager.start_container.side_effect = ContainerError("Docker container failed to start")
    response = client.post("/run", json={"instruction": "Generate code but fail Docker."})
    assert response.status_code == 500
    assert ("container" in _message(_json(response)).lower()) or ("docker" in _message(_json(response)).lower())
    code_generator.generate.assert_awaited_once()
    container_manager.start_container.assert_awaited_once()
    assert execution_manager.active_execution_id is None
