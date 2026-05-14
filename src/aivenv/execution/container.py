"""Docker container lifecycle management for isolated execution."""

from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

try:
    import docker
except ModuleNotFoundError:  # pragma: no cover
    docker = None  # type: ignore[assignment]

try:
    from requests.exceptions import ReadTimeout
except ModuleNotFoundError:  # pragma: no cover
    ReadTimeout = TimeoutError  # type: ignore[assignment]

_END_OF_STREAM = object()


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
        script_path: str | Path,
        *,
        output_dir: str | Path | None = None,
        command: Iterable[str] | None = None,
        name: str | None = None,
        environment: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> Any:
        """Start a Docker container that runs the generated script."""

        script = Path(script_path).resolve(strict=True)
        if not script.is_file():
            raise ContainerManagerError(f"script path is not a file: {script}")

        output = Path(output_dir).resolve() if output_dir is not None else script.parent / "output"
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
        if name:
            run_kwargs["name"] = name
        if environment:
            run_kwargs["environment"] = dict(environment)

        self._container = self._client.containers.run(**run_kwargs)
        return self._container

    async def start_container(self, script_path: str | Path, **kwargs: Any) -> Any:
        """Async wrapper for start()."""

        return await asyncio.to_thread(self.start, script_path, **kwargs)

    async def stream_logs(self, container: Any | None = None) -> list[str]:
        """Return container logs as decoded lines."""

        active_container = container or self._container
        if active_container is None:
            raise ContainerManagerError("no container is available for log streaming")

        raw_logs = await asyncio.to_thread(active_container.logs, stdout=True, stderr=True)
        text = _decode_chunk(raw_logs)
        return text.splitlines()

    async def stream_logs_live(self, container: Any | None = None) -> AsyncIterator[str]:
        """Yield log chunks from the container as they arrive."""
        active_container = container or self._container
        if active_container is None:
            raise ContainerManagerError("no container is available for log streaming")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _reader() -> None:
            try:
                for chunk in active_container.logs(stream=True, follow=True, stdout=True, stderr=True):
                    text = _decode_chunk(chunk)
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            except Exception:
                pass
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_reader, daemon=True).start()

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    def stop(
        self,
        container: Any | None = None,
        *,
        timeout: float = 10,
        kill_timeout: float = 2,
    ) -> None:
        """Stop a running container, escalating from SIGTERM to SIGKILL on timeout."""

        active_container = container or self._container
        if active_container is None:
            raise ContainerManagerError("no container is available to stop")

        active_container.kill(signal=signal.SIGTERM)
        if not _wait_for_container(active_container, timeout):
            active_container.kill(signal=signal.SIGKILL)
            _wait_for_container(active_container, kill_timeout)

        if active_container is self._container:
            self._container = None

    async def kill(self, container: Any | None = None) -> None:
        """Kill a container immediately."""

        active_container = container or self._container
        if active_container is None:
            return
        await asyncio.to_thread(active_container.kill)
        if active_container is self._container:
            self._container = None

    async def wait(self, container: Any | None = None) -> None:
        """Wait for a container to stop."""

        active_container = container or self._container
        if active_container is not None:
            await asyncio.to_thread(active_container.wait)

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


def _decode_chunk(chunk: Any) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    if isinstance(chunk, str):
        return chunk
    return str(chunk)


def _wait_for_container(container: Any, timeout: float) -> bool:
    try:
        container.wait(timeout=timeout)
        return True
    except (TimeoutError, ReadTimeout):
        return False
    except TypeError:
        container.wait()
        return True


__all__ = ["ContainerManager", "ContainerManagerError"]
