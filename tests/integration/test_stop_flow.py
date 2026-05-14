"""Integration tests for the POST /stop lifecycle."""

from __future__ import annotations

import asyncio
import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient


PUBLIC_URL = "https://stop-flow-test.ngrok.io"
RUN_PAYLOAD = {"instruction": "print a heartbeat until stopped"}


@dataclass(slots=True)
class FakeContainer:
    id: str


class FakeCodeGenerator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(self, instruction: str, execution_id: str | None = None) -> str:
        self.calls.append({"instruction": instruction, "execution_id": execution_id})
        return "import time\nwhile True:\n    print('running', flush=True)\n    time.sleep(1)\n"

    async def generate_code(self, instruction: str, execution_id: str | None = None) -> str:
        return await self.generate(instruction, execution_id)


class FakeDocker:
    def __init__(self, *, hang_on_stop: bool = False) -> None:
        self.hang_on_stop = hang_on_stop
        self.container_id = "container-stop-flow"
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.killed: list[str] = []

    async def start_container(self, *args: Any, **kwargs: Any) -> FakeContainer:
        self.started.append(self.container_id)
        return FakeContainer(self.container_id)

    async def start(self, *args: Any, **kwargs: Any) -> FakeContainer:
        return await self.start_container(*args, **kwargs)

    async def run(self, *args: Any, **kwargs: Any) -> FakeContainer:
        return await self.start_container(*args, **kwargs)

    async def stop_container(self, container: str | FakeContainer, *, timeout: float | None = None) -> None:
        container_id = container if isinstance(container, str) else container.id
        self.stopped.append(container_id)
        if self.hang_on_stop:
            await asyncio.sleep(60)

    async def stop(self, container: str | FakeContainer, *, timeout: float | None = None) -> None:
        await self.stop_container(container, timeout=timeout)

    async def kill_container(self, container: str | FakeContainer) -> None:
        container_id = container if isinstance(container, str) else container.id
        self.killed.append(container_id)

    async def kill(self, container: str | FakeContainer) -> None:
        await self.kill_container(container)


class FakeNgrok:
    def __init__(self) -> None:
        self.opened: list[int | None] = []
        self.closed = 0

    async def open_tunnel(self, port: int | None = None) -> str:
        self.opened.append(port)
        return PUBLIC_URL

    async def start_tunnel(self, port: int | None = None) -> str:
        return await self.open_tunnel(port)

    async def connect(self, port: int | None = None) -> str:
        return await self.open_tunnel(port)

    async def close_tunnel(self) -> None:
        self.closed += 1

    async def stop_tunnel(self) -> None:
        await self.close_tunnel()


@dataclass(slots=True)
class Harness:
    client: TestClient
    docker: FakeDocker
    ngrok: FakeNgrok
    temp_dir: Path


def _import_attr(candidates: tuple[tuple[str, str], ...]) -> Any:
    for module_name, attr_name in candidates:
        try:
    sig = inspect.signature(target)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return target(**kwargs)
        if hasattr(module, attr_name):
            return getattr(module, attr_name)
    raise AssertionError("Could not locate aivenv app factory or execution manager")


def _call(target: Callable[..., Any], **kwargs: Any) -> Any:
    sig = imspect.signature(target)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return target(**kargs)
    return target(**{k: v for k, v in kwargs.items() if k in sig.parameters})


def _harness(tmp_path: Path, *, cleanup: bool = False, hang: bool = False) -> Harness:
    manager_cls = _import_attr((
        ("aivenv.execution_manager", "ExecutionManager"),
        ("aivenv.execution.manager", "ExecutionManager"),
        ("aivenv.manager", "ExecutionManager"),
    ))
    create_app = _import_attr((
        ("aivenv.api", "create_app"),
        ("aivenv.api.server", "create_app"),
        ("aivenv.server", "create_app"),
    ))
    docker = FakeDocker(hang_on_stop=hang)
    ngrok = FakeNgrok()
    manager = _call(manager_cls, code_generator=FakeCodeGenerator(), container_manager=docker, ngrok_manager=ngrok, temp_dir=tmp_path, cleanup=cleanup, cleanup_temp_files=cleanup, stop_timeout=0.01, stop_timeout_seconds=0.01)
    for name, value in {"code_generator": FakeCodeGenerator(), "container_manager": docker, "ngrok_manager": ngrok, "temp_dir": tmp_path, "cleanup_temp_files": cleanup, "stop_timeout_seconds": 0.01}.items():
        if hasattr(manager, name):
            setattr(manager, name, value)
    app = _call(create_app, execution_manager=manager, manager=manager)
    return Harness(TestClient(app), docker, ngrok, tmp_path)


def _run(client: TestClient) -> dict[str, Any]:
    response = client.post("/run", json=RUN_PAYLOAD)
    assert response.status_code == 202, response.text
    body = response.json()
    assert isinstance(body["execution_id"], str)
    assert body["result_url"] == PUBLIC_URL
    return body


@pytest.fixture()
def harness_factory(tmp_path: Path) -> Callable[..., Harness]:
    def build(*, cleanup: bool = False, hang: bool = False) -> Harness:
        return _harness(tmp_path, cleanup=cleanup, hang=hang)
    return build


def test_stop_returns_200_for_correct_execution_id(harness_factory: Callable[..., Harness]) -> None:
    h = harness_factory()
    run = _run(h.client)
    response = h.client.post("/stop", json={"execution_id": run["execution_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["execution_id"] == run["execution_id"]
    assert h.docker.stopped == [h.docker.container_id]
    assert h.docker.killed == []
    assert h.ngrok.closed == 1


def test_stop_returns_404_when_no_active_session(harness_factory: Callable[..., Harness]) -> None:
    h = harness_factory()
    response = h.client.post("/stop", json={"execution_id": "missing"})
    assert response.status_code == 404, response.text
    assert h.docker.stopped == []
    assert h.docker.killed == []


def test_stop_escalates_to_sigkill_after_timeout(harness_factory: Callable[..., Harness]) -> None:
    h = harness_factory(hang=True)
    run = _run(h.client)
    response = h.client.post("/stop", json={"execution_id": run["execution_id"]})
    assert response.status_code == 200, response.text
    assert h.docker.stopped == [h.docker.container_id]
    assert h.docker.killed == [h.docker.container_id]


def test_stop_cleanup_flag_removes_temp_files(harness_factory: Callable[..., Harness]) -> None:
    h = harness_factory(cleanup=True)
    run = _run(h.client)
    artifacts = list(h.temp_dir.rglob(f"*{run['execution_id']}*"))
    assert artifacts, "run should persist a generated artifact that includes the execution_id"
    response = h.client.post("/stop", json={"execution_id": run["execution_id"]})
    assert response.status_code == 200, response.text
    assert [p for p in artifacts if p.exists()] == []


def test_stop_returns_to_idle_and_accepts_new_run(harness_factory: Callable[..., Harness]) -> None:
    h = harness_factory()
    first = _run(h.client)
    response = h.client.post("/stop", json={"execution_id": first["execution_id"]})
    assert response.status_code == 200, response.text
    second = _run(h.client)
    assert second["execution_id"] != first["execution_id"]
    assert len(h.docker.started) == 2
