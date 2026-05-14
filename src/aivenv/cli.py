"""Command line entrypoint for the aivenv service."""

from __future__ import annotations

import asyncio
import importlib
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from types import FrameType
from typing import Any, Awaitable, Callable, Iterable


import click
import uvicorn


DEFAULT_API_PORT = 8080
DEFAULT_LOG_PORT = 8081
DEFAULT_MODEL = "gpt-4o"
DEFAULT_LOG_LEVEL = "info"
SERVER_START_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class StartConfig:
    """Runtime configuration collected from CLI flags and environment variables."""

    openai_api_key: str
    ngrok_authtoken: str
    port: int = DEFAULT_API_PORT
    log_port: int = DEFAULT_LOG_PORT
    model: str = DEFAULT_MODEL
    cleanup: bool = True
    log_level: str = DEFAULT_LOG_LEVEL


ManagedServer = uvicorn.Server
_managed_servers: set[ManagedServer] = set()
_external_shutdown_hooks: tuple[tuple[str, str], ...] = (
    ("aivenv.lifecycle", "graceful_shutdown"),
    ("aivenv.runtime", "graceful_shutdown"),
    ("aivenv.execution", "graceful_shutdown"),
)


class StartupError(click.ClickException):
    """Human-readable startup failure raised before long-running servers start."""


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
def start(
    openai_api_key: str | None,
    ngrok_authtoken: str | None,
    port: int,
    log_port: int,
    model: str,
    cleanup: bool,
    log_level: str,
) -> None:
@click.option(
    "--ngrok-authtoken",
    envvar="NGROK_AUTHTOKEN",
    help="ngrok authentication token. Can also be set with NGROK_AUTHTOKEN.",
)
@click.option("--port", default=DEFAULT_API_PORT, show_default=True, type=click.IntRange(1, 65535))
@click.option("--log-port", default=DEFAULT_LOG_PORT, show_default=True, type=click.IntRange(1, 65535))
@click.option("--model", default=DEFAULT_MODEL, show_default=True, help="OpenAI model name.")
@click.option("--cleanup/--no-cleanup", default=True, show_default=True, help="Clean up runtime resources on shutdown.")
@click.option(
    "--log-level",
    default=DEFAULT_LOG_LEVEL,
    show_default=True,
    type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"], case_sensitive=False),
)
) -> None:
    openai_api_key: str | None,
    ngrok_authtoken: str | None,
    port: int,
    log_port: int,
def _build_start_config(
    *,
    openai_api_key: str | None,
    ngrok_authtoken: str | None,
    port: int,
    log_port: int,
    model: str,
    cleanup: bool,
    log_level: str,
) -> StartConfig:
        log_port=log_port,
        model=model,
        cleanup=cleanup,
        log_level=log_level,
    )

    try:
        asyncio.run(_run_start(config))
    except KeyboardInterrupt:
        raise click.exceptions.Exit(130) from None


def _build_start_config(
    *,
    openai_api_key: str | None,
    ngrok_authtoken: str | None,
    port: int,
) -> StartConfig:
    model: str,
    cleanup: bool,
    log_level: str,
J -> StartConfig:
    """Validate CLI/env configuration and return a normalized StartConfig."""

    missing: list[str] = []
    normalized_openai_key = (openai_api_key or "").strip()
    normalized_ngrok_token = (ngrok_authtoken or "").strip()
    normalized_model = model.strip()

    if not normalized_openai_key:
        missing.append("--openai-api-key or OPENAI_API_KEY")
    if not normalized_ngrok_token:
        missing.append("--ngrok-authtoken or NGROK_AUTHTOKEN")
    if not normalized_model:
        missing.append("--model")
    if port == log_port:
        raise StartupError("--port and --log-port must use different ports.")
    if missing:
        raise StartupError("Missing required configuration: " + ", ".join(missing) + ".")

    return StartConfig(
        openai_api_key=normalized_openai_key,
        ngrok_authtoken=normalized_ngrok_token,
        port=port,
        log_port=log_port,
        model=normalized_model,
        cleanup=cleanup,
        log_level=log_level.lower(),
    )


def _validate_docker_available() -> None:
    """Fast-fail when Docker is missing or the daemon cannot be reached."""

    try:
        docker_module = importlib.import_module("docker")
    except ModuleNotFoundError:
        _validate_docker_cli_available()
        return

    try:
        client = docker_module.from_env()
        try:
            client.ping()
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
    except Exception as exc:
        raise StartupError(
            "Docker is not available. Start Docker Desktop or the Docker daemon before running aivenv start."
        ) from exc


def _validate_docker_cli_available() -> None:
    docker_path = shutil.which("docker")
    if docker_path is None:
        raise StartupError(
            "Docker is not installed or not on PATH. Install Docker and start the daemon before running aivenv start."
        )

    try:
        subprocess.run(
            [docker_path, "info", "--format", "{{json .ServerVersion}}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise StartupError(
            "Docker is not available. Start Docker Desktop or the Docker daemon before running aivenv start."
        ) from exc


async def _run_start(config: StartConfig) -> None:
    click.echo("aivenv: validating Docker availability...")
    _validate_docker_available()
    click.echo("aivenv: Docker is available.")

    os.environ["OPENAI_API_KEY"] = config.openai_api_key
    os.environ["NGROK_AUTHTOKEN"] = config.ngrok_authtoken

    log_app = _create_log_app(config)
    api_app = _create_api_app(config)

    log_server = _create_uvicorn_server(log_app, config.log_port, config.log_level)
    api_server = _create_uvicorn_server(api_app, config.port, config.log_level)
    _managed_servers.update({log_server, api_server})

    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, (api_server, log_server))

    log_task = asyncio.create_task(log_server.serve(), name="aivenv-log-server")
    try:
        await _wait_for_server_start(log_server, log_task, "log server")
        click.echo(f"aivenv: log server started at http://127.0.0.1:{config.log_port}")
        click.echo("aivenv: ngrok tunnel will target the log server when execution starts.")
        click.echo(f"aivenv: starting API server at http://127.0.0.1:{config.port}")
        click.echo("aivenv: awaiting requests. Send POST /run to start an execution.")
        await api_server.serve()
        api_server.should_exit = True
        log_server.should_exit = True
        await graceful_shutdown()
        await _await_background_task(log_task)
        _managed_servers.discard(api_server)
        _managed_servers.discard(log_server)
        if config.cleanup:
            click.echo("aivenv: cleanup complete.")


def _create_api_app(config: StartConfig) -> Any:
    return _call_app_factory(
        module_name="aivenv.api",
        factory_names=("create_api_app", "create_app", "app"),
        config=config,
        label="API server",
    )


def _create_log_app(config: StartConfig) -> Any:
    return _call_app_factory(
        module_name="aivenv.log_server",
        factory_names=("create_log_app", "create_app", "app"),
        config=config,
            previous(received_signal, frame)
    )


def _call_app_factory(*, module_name: str, factory_names: Iterable[str], config: StartConfig, label: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise StartupError(f"Unable to start {label}: required module '{module_name}' was not found.") from exc

    for factory_name in factory_names:
        candidate = getattr(module, factory_name, None)
        if candidate is None:
            continue
        if factory_name == "app" and not callable(candidate):
            return candidate
        if callable(candidate):
            try:
                return candidate(config)
            except TypeError:
                return candidate()

    names = ", ".join(factory_names)
    raise StartupError(f"Unable to start {label}: '{module_name}' must expose one of {names}.")


def _create_uvicorn_server(app: Any, port: int, log_level: str) -> uvicorn.Server:
    uvicorn_config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level=log_level,
        lifespan="on",
        access_log=log_level in {"debug", "trace"},
    )
    return uvicorn.Server(uvicorn_config)
            previous(received_signal, frame)

async def _wait_for_server_start(server: uvicorn.Server, task: asyncio.Task[Any], label: str) -> None:
    deadline = asyncio.get_running_loop().time() + SERVER_START_TIMEOUT_SECONDS
    while not server.started:
        if task.done():
            exc = task.exception()
            message = f"{label} exited before startup completed."
            if exc is not None:
                raise StartupError(f"{message} {exc}") from exc
            raise StartupError(message)
        if asyncio.get_running_loop().time() >= deadline:
            server.should_exit = True
            raise StartupError(f"Timed out waiting for {label} to start.")
        await asyncio.sleep(0.05)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, servers: Iterable[uvicorn.Server]) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda sig=sig: asyncio.create_task(_handle_shutdown_signal(sig, servers)))
        except (NotImplementedError, RuntimeError):
            previous_handler = signal.getsignal(sig)

            def _handler(received: int, frame: FrameType | None, *, previous: Any = previous_handler) -> None:
                asyncio.create_task(_handle_shutdown_signal(signal.Signals(received), servers))
                if callable(previous) and previous not in (signal.SIG_DFL, signal.SIG_IGN):
                    previous(coreceived, frame)

            signal.signal(sig, _handler)


async def _handle_shutdown_signal(sig: signal.Signals, servers: Iterable[uvicorn.Server]) -> None:
    click.echo(f"aivenv: received {sig.name}; shutting down gracefully...")
    for server in servers:
        server.should_exit = True
    await graceful_shutdown()


async def graceful_shutdown() -> None:
    """Stop managed servers and delegate runtime cleanup to the execution subsystem when present."""

    for server in tuple(_managed_servers):
        server.should_exit = True

    for module_name, function_name in _external_shutdown_hooks:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        shutdown = getattr(module, function_name, None)
        if not callable(shutdown):
            continue
        result = shutdown()
        if asyncio.iscoroutine(result):
            await result
        return


async def _await_background_task(task: asyncio.Task[Any]) -> None:
    if task.done():
        task.result()
        return

    try:
        await asyncio.wait_for(task, timeout=SERVER_START_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    cli()
