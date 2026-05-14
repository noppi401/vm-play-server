"""Execution lifecycle orchestration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


class ConflictError(RuntimeError):
    """Raised when an execution is already running."""


class NotFoundError(RuntimeError):
    """Raised when no matching execution is running."""


@dataclass(slots=True)
class RunSession:
    session_id: str
    source_path: Path
    container: Any
    tunnel: Any | None = None
    public_url: str | None = None
    workdir: Path | None = None


class ExecutionManager:
    """Coordinate code generation, container startup, tunnel creation, and cleanup."""

    def __init__(
        self,
        code_generator: Any,
        container_manager: Any,
        ngrok_manager: Any,
        *,
        work_dir: str | os.PathLike[str] | None = None,
        cleanup_on_stop: bool = True,
        log_buffer_factory: Any | None = None,
        logger: logging.Logger | None = None,
        **_: Any,
    ) -> None:
        self.code_generator = code_generator
        self.container_manager = container_manager
        self.ngrok_manager = ngrok_manager
        self.work_dir = Path(work_dir) if work_dir is not None else None
        self.cleanup_on_stop = cleanup_on_stop
        self.log_buffer_factory = log_buffer_factory
        self.logger = logger or logging.getLogger(__name__)
        self._lock = asyncio.Lock()
        self._session: RunSession | None = None

    @property
    def current_session(self) -> RunSession | None:
        return self._session

    async def start_run(self, prompt: str, *, session_id: str | None = None) -> RunSession:
        async with self._lock:
            if self._session is not None:
                raise ConflictError("an execution session is already running")

            run_id = session_id or uuid4().hex
            workdir = Path(tempfile.mkdtemp(prefix="aivenv-", dir=self.work_dir))
            source_path = workdir / "app.py"
            session: RunSession | None = None

            try:
                code = await self._generate_code(prompt)
                source_path.write_text(code, encoding="utf-8")

                container = await self._start_container(source_path, run_id)
                try:
                    tunnel = await self._open_tunnel(container)
                except Exception as _tunnel_exc:
                    self.logger.warning("ngrok tunnel unavailable: %s", _tunnel_exc, exc_info=True)
                    tunnel = None
                session = RunSession(
                    session_id=run_id,
                    source_path=source_path,
                    container=container,
                    tunnel=tunnel,
                    public_url=self._extract_public_url(tunnel),
                    workdir=workdir,
                )
                self._session = session
                if self.log_buffer_factory is not None:
                    log_buffer = self.log_buffer_factory(run_id)
                    asyncio.create_task(
                        self._stream_logs_to_buffer(session, log_buffer),
                        name=f"aivenv-logs-{run_id}",
                    )
                return session
            except Exception:
                if session is not None:
                    await self._stop_session(session, cleanup=True)
                elif self.cleanup_on_stop:
                    shutil.rmtree(workdir, ignore_errors=True)
                raise

    async def stop_run(self, *, session_id: str | None = None, cleanup: bool | None = None) -> None:
        async with self._lock:
            session = self._session
            if session is None:
                raise NotFoundError("no execution session is running")
            if session_id is not None and session.session_id != session_id:
                raise NotFoundError(f"execution session {session_id!r} was not found")

            self._session = None
            await self._stop_session(session, cleanup=self.cleanup_on_stop if cleanup is None else cleanup)

    async def _generate_code(self, prompt: str) -> str:
        generate = getattr(self.code_generator, "generate", None) or self.code_generator
        if not callable(generate):
            raise TypeError("code_generator must be callable or expose generate()")
        result = generate(prompt)
        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, str):
            raise TypeError("code generator returned non-string source")
        return result

    async def _start_container(self, source_path: Path, run_id: str) -> Any:
        start = getattr(self.container_manager, "start_container", None) or getattr(self.container_manager, "start", None)
        if start is None:
            raise TypeError("container_manager must expose start_container() or start()")
        result = start(source_path, run_id=run_id)
        if hasattr(result, "__await__"):
            return await result
        return result

    async def _open_tunnel(self, container: Any) -> Any:
        open_tunnel = getattr(self.ngrok_manager, "open_tunnel", None) or getattr(self.ngrok_manager, "open", None)
        if open_tunnel is None:
            raise TypeError("ngrok_manager must expose open_tunnel() or open()")
        try:
            result = open_tunnel(self._extract_port(container))
        except TypeError:
            result = open_tunnel()
        if hasattr(result, "__await__"):
            return await result
        return result

    async def _stream_logs_to_buffer(self, session: RunSession, log_buffer: Any) -> None:
        stream_fn = getattr(self.container_manager, "stream_logs_live", None)
        if stream_fn is None:
            return
        try:
            async for chunk in stream_fn(session.container):
                await log_buffer.write(chunk)
        except Exception as exc:
            self.logger.warning("log streaming error: %s", exc)
        finally:
            await log_buffer.done()

    async def _stop_session(self, session: RunSession, *, cleanup: bool) -> None:
        with contextlib.suppress(Exception):
            close = getattr(self.ngrok_manager, "close_tunnel", None) or getattr(self.ngrok_manager, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

        with contextlib.suppress(Exception):
            stop = getattr(self.container_manager, "stop", None)
            if stop is not None:
                result = stop(session.container)
                if hasattr(result, "__await__"):
                    await result

        if cleanup and session.workdir is not None:
            shutil.rmtree(session.workdir, ignore_errors=True)

    @staticmethod
    def _extract_port(container: Any) -> int:
        if isinstance(container, dict):
            return int(container.get("port") or container.get("host_port") or 8000)
        return int(getattr(container, "port", getattr(container, "host_port", 8000)))

    @staticmethod
    def _extract_public_url(tunnel: Any) -> str | None:
        if isinstance(tunnel, str):
            return tunnel
        if isinstance(tunnel, dict):
            return tunnel.get("public_url") or tunnel.get("url")
        return getattr(tunnel, "public_url", getattr(tunnel, "url", None))
