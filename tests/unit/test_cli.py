from __future__ import annotations

import asyncio
from typing import Any

from click.testing import CliRunner

from aivenv import cli as cli_module


class DummyServer:
    instances: list["DummyServer"] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.started = False
        self.should_exit = False
        DummyServer.instances.append(self)

    async def serve(self) -> None:
        self.started = True
        while not self.should_exit:
            await asyncio.sleep(0.01)


class DummyDockerClient:
    def __init__(self) -> None:
        self.closed = False
        self.pinged = False

    def ping(self) -> bool:
        self.pinged = True
        return True

    def close(self) -> None:
        self.closed = True


def test_start_requires_configuration() -> None:
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["start"], env={})

    assert result.exit_code != 0
    assert "Missing required configuration" in result.output
    assert "OPENAI_API_KEY" in result.output
    assert "NGROK_AUTHTOKEN" in result.output


def test_validate_docker_available_uses_docker_sdkm(monkeypatch: Any) -> None:
    client = DummyDockerClient()

    class DockerModule:
        @staticmethod
        def from_env() -> DummyDockerClient:
            return client

    def import_module(name: str) -> Any:
        if name == "docker":
            return DockerModule
        return __import__(name)

    monkeypatch.setattr(cli_module.importlib, "import_module", import_module)

    cli_module._validate_docker_available()

    assert client.pinged is True
    assert client.closed is True


def test_start_wires_servers_and_prints_status(monkeypatch: Any) -> None:
    DummyServer.instances.clear()

    async def stop_after_start(config: cli_module.StartConfig) -> None:
        await asyncio.sleep(0.05)
        for server in DummyServer.instances:
            server.should_exit = True

    monkeypatch.setattr(cli_module, "_validate_docker_available", lambda: None)
    monkeypatch.setattr(cli_module, "_create_api_app", lambda config: object())
    monkeypatch.setattr(cli_module, "_create_log_app", lambda config: object())
    monkeypatch.setattr(cli_module.uvicorn, "Server", DummyServer)
    monkeypatch.setattr(cli_module.uvicorn, "Config", lambda **kwargs: kwargs)
    monkeypatch.setattr(cli_module, "graceful_shutdown", lambda: asyncio.sleep(0))

    original_run_start = cli_module._run_start

    async def wrapped_run_start(config: cli_module.StartConfig) -> None:
        stopper = asyncio.create_task(stop_after_start(config))
        try:
            await original_run_start(config)
        finally:
            await stopper

    monkeypatch.setattr(cli_module, "_run_start", wrapped_run_start)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        [
            "start",
            "--openai-api-key",
            "sk-test",
            "--ngrok-authtoken",
            "ngrok-test",
            "--port",
            "8090",
            "--log-port",
            "8091",
            "--model",
            "gpt-test",
            "--no-cleanup",
            "--log-level",
            "debug",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Docker is available" in result.output
    assert "log server started at http://127.0.0.1:8091" in result.output
    assert "starting API server at http://127.0.0.1:8090" in result.output
    assert "awaiting requests" in result.output
    assert len(DummyServer.instances) == 2
    assert DummyServer.instances[0].config["port"] == 8091
    assert DummyServer.instances[1].config["port"] == 8090
