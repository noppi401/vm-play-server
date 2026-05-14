"""Docker container lifecycle management for isolated execution."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol
try:
    from requests.exceptions import ReadTimeout
except ModuleNotFoundError:  # pragma: no cover - requests is installed with docker-py
    ReadTimeout = TimeoutError  # type: ignore[assignment]

except ModuleNotFoundError:  # pragma: no cover - exercised only when dependency is absent
    docker = None  # type: ignore[assignment]
_END_OF_STREAM = object()
except ModuleNotFoundError:  # pragma: no cover - exercised only when dependency is absent
_END_OF_STREAM = object()


class _LogBuffer(Protocol):
    async def write(self, chunk: str) -> None:
        ...

    async def done(self) -> None:
        ...


class ContainerManagerError(RuntimeError):
    """Raised when container lifecycle operations cannot be completed."""


class ContainerManager:
    """Manage Docker containers used to run generated scripts."""

    SCRIPT_PATH = "/workspace/script.py"
    OUTPUT_PATH = "/output"
    UID = "1000:1000"
    LABELS = {"aivenv": "true", "aivenv.managed": "true"}

    def __init__(
        self,
        *,
        image: str,
        cpu_limit: float,
        memory_limit: str,
        client: Any | None = None,
    ) -> None:
        if not image.strip():
            raise ContainerManagerError("container image must not be empty")
        if cpu_limit <= 0:
            raise ContainerManagerError("cpu_limit must be greater than zero")
        if not memory_limit.strip():
            raise ContainerManagerError("memory_limit must not be empty")

        if client is None:
            if docker is None:
                raise ContainerManagerError("docker package is required to manage containers")
            client = docker.from_env()

        self._client = client
        self._image = image
        self._cpu_limit = float(cpu_limit)
        self._memory_limit = memory_limit
        self._container: Any | None = None

    @property
    def container(self) -> Any | None:
        """Return the most recently started container, if any."""

        return self._container

    def start(
        self,
        *,
        script_path: str | Path,
        output_dir: str | Path,
        command: Iterable[str] | None = None,
        name: str | None = None,
        environment: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> Any:
        """Start a locked-down Docker container for the generated script."""

        script = Path(script_path).resolve(strict=True)
        if not script.is_file():
            raise ContainerManagerError(f"script path is not a file: {script}")

        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)

        labels = dict(self.LABELS)
        if run_id:
            labels["aivenv.run_id"] = run_id

        run_kwargs: dict[str, Any] = {
            "image": self._image,
            "command": list(command) if command is not None else ["python", self.SCRIPT_PATH],
            "detach": True,
            "stdout": True,
            "stderr": True,
            "user": self.UID,
            "network_mode": "none",
            "working_dir": self.OUTPUT_PATH,
            "volumes": {
                str(script): {"bind": self.SCRIPT_PATH, "mode": "ro"},
                str(output): {"bind": self.OUTPUT_PATH, "mode": "rw"},
            },
            "labels": labels,
            "mem_limit": self._memory_limit,
            "nano_cpus": int(self._cpu_limit * 1_000_000_000),
        }
        active_container = container or self._container
        if active_container is None:
            raise ContainerManagerError("no container is available to stop")

        active_container.kill(signal=signal.SIGTERM)
        if not _wait_for_container(active_container, timeout):
            active_container.kill(signal=signal.SIGKILL)
            _wait_for_container(active_container, kill_timeout)

        if active_container is self._container:
            self._container = None

    def cleanup_orphans(self) -> int:
        """Remove containers previously created by this manager."""

        containers = self._client.containers.list(
            all=True,
            filters={"label": ["aivenv=true", "aivenv.managed=true"]},
        )

        removed = 0
        for container in containers:
            container.remove(force=True)
            removed += 1
        return removed
            run_kwargs["name"] = name
        if environment:
            run_kwargs["environment"] = dict(environment)

        self._container = self._client.containers.run(**run_kwargs)
        return self._container

    async def stream_logs(self, log_buffer: _LogBuffer, container: Any | None = None) -> None:
        """Stream Docker stdout/stderr into a LogBuffer until the stream ends."""

        active_container = container or self._container
        if active_container is None:
            raise ContainerManagerError("no container is available for log streaming")

        iterator = iter(active_container.logs(stream=True, follow=True, stdout=True, stderr=True))
        try:
            while True:
        removed = 0
        for container in containers:
            container.remove(force=True)
            removed += 1
    except (TimeoutError, ReadTimeout):
        return False
        return chunk.decode("utf-8", errors="replace")
    if isinstance(chunk, str):
        return chunk
    return str(chunk)
def _next_chunk(iterator: Any) -> Any:
    try:
        return next(iterator)
    except (TimeoutError, ReadTimeout):
        return _END_OF_STREAM

    except (TimeoutError, ReadTimeout):
        return False
    if isinstance(chunk, bytes):
    except (TimeoutError, ReadTimeout):
    if isinstance(chunk, str):
        return chunk
    return str(chunk)


def _wait_for_container(container: Any, timeout: float) -> bool:
    try:
        container.wait(timeout=timeout)
        return True
    except TimeoutError:
        return False
    except TypeError:
        container.wait()
        return True


__all__ = ["ContainerManager", "ContainerManagerError"]