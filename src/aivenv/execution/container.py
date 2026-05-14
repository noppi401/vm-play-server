"""Docker container lifecycle management for isolated execution."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

try:
    import docker
except ModuleNotFoundError:  # pragma: no cover - exercised only when dependency is absent
    docker = None  # type: ignore[assignment]

try:
    from requests.exceptions import ReadTimeout
except ModuleNotFoundError:  # pragma: no cover - requests is installed with docker-py
    ReadTimeout = TimeoutError  # type: ignore[assignment]

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
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        _ensure_output_dir_writable(output, self.UID)

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
        if name:
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
                chunk = await asyncio.to_thread(_next_chunk, iterator)
                if chunk is _END_OF_STREAM:
                    break
                await log_buffer.write(_decode_chunk(chunk))
        finally:
            await log_buffer.done()

    def stop(
        self,
        *,
        container: Any | None = None,
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

    def cleanup_orphans(self) -> int:

def _ensure_output_dir_writable(path: Path, uid_spec: str) -> None:
    uid, gid = _parse_uid_spec(uid_spec)
    if hasattr(os, "chown"):
        try:
            os.chown(path, uid, gid)
        except PermissionError:
            path.chmod(path.stat().st_mode | 0o777)
        except OSError:
            path.chmod(path.stat().st_mode | 0o777)
    else:
        path.chmod(path.stat().st_mode | 0o777)

    if not _mode_allows_user_write(path, uid, gid):
        raise ContainerManagerError(f"output directory is not writable by uid {uid_spec}: {path}")


def _parse_uid_spec(uid_spec: str) -> tuple[int, int]:
    uid_text, _, gid_text = uid_spec.partition(":")
    uid = int(uid_text)
    gid = int(gid_text or uid_text)
    return uid, gid


def _mode_allows_user_write(path: Path, uid: int, gid: int) -> bool:
    stat_result = path.stat()
    mode = stat_result.st_mode
    if stat_result.st_uid == uid and mode & 0o200:
        return True
    if stat_result.st_gid == gid and mode & 0o020:
        return True
    return bool(mode & 0o002)
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


def _next_chunk(iterator: Any) -> Any:
    try:
        return next(iterator)
    except StopIteration:
        return _END_OF_STREAM
    except (TimeoutError, ReadTimeout):
        return _END_OF_STREAM


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