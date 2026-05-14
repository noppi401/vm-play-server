from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import shutil
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConflictError(RuntimeError):
    pass


class NotFoundError(RuntimeError):
    pass


@dataclass(slots=True)
class RunSession:
    session_id: str
    source_path: Path
    container: Any
    tunnel: Any | None = None
    public_url: str | None = None
    log_task: asyncio.Task[None] | None = None
    workdir: Path | None = None


class ExecutionManager:
    def __init__(
        self,
        code_generator: Any,
        container_manager: Any,
        ngrok_manager: Any,
        *,
        work_dir: str | os.PathLike[str] | None = None,
        cleanup_on_stop: bool = True,
        term_timeout: float = 10.0,
        kill_timeout: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.code_generator = code_generator
        self.container_manager = container_manager
        self.ngrok_manager = ngrok_manager
        self.work_dir = Path(work_dir) if work_dir is not None else None
        self.cleanup_on_stop = cleanup_on_stop
        self.term_timeout = term_timeout
        self.kill_timeout = kill_timeout
        self.logger = logger or logging.getLogger(__name__)
        self._lock = asyncio.Lock()
        self._session: RunSession | None = None

    @property
    def current_session(self) -> RunSession | None:
        return self._session

    async def start_run(self, prompt: str, *, session_id: str = 'default') -> RunSession:
        async with self._lock:
            safe_session_id = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in session_id).strip('._-')
            source_path = workdir / f'{safe_session_id or "default"}.py'
                raise ConflictError('an execution session is already running')

            workdir = Path(tempfile.mkdtemp(prefix='aivenv-', dir=self.work_dir))
            source_path = workdir / 'app.py'
            session: RunSession | None = None

            try:
                code = await self._generate_code(prompt)
                source_path.write_text(code, encoding='utf-8')

                container = await self._start_container(source_path)
                session = RunSession(session_id=session_id, source_path=source_path, container=container, workdir=workdir)
                session.log_task = asyncio.create_task(self._stream_logs(session), name=f'aivenv-logs-{session_id}')

                tunnel = await self._open_tunnel(container)
                session.tunnel = tunnel
                session.public_url = self._extract_public_url(tunnel)
                self._session = session
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
                raise NotFoundError('no execution session is running')
            if session_id is not None and session.session_id != session_id:
                raise NotFoundError(f'execution session {session_id!r} was not found')

            self._session = None
            await self._stop_session(session, cleanup=self.cleanup_on_stop if cleanup is None else cleanup)

    def emergency_stop(self) -> asyncio.Task[None] | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None

        return loop.create_task(self._emergency_stop(), name='aivenv-emergency-stop')

    async def _emergency_stop(self) -> None:
        async with self._lock:
            session = self._session
            self._session = None

        if session is not None:
            with contextlib.suppress(Exception):
                await self._stop_session(session, cleanup=True)

    async def _stop_session(self, session: RunSession, *, cleanup: bool) -> None:
        if session.log_task is not None:
            session.log_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.log_task

        if session.tunnel is not None:
            with contextlib.suppress(Exception):
                await self._close_tunnel(session.tunnel)

        with contextlib.suppress(Exception):
            await self._terminate_container(session.container)

        if cleanup and session.workdir is not None:
            shutil.rmtree(session.workdir, ignore_errors=True)

    async def _generate_code(self, prompt: str) -> str:
        if hasattr(self.code_generator, 'generate'):
            result = self.code_generator.generate(prompt)
        elif callable(self.code_generator):
            result = self.code_generator(prompt)
        else:
            raise TypeError('code_generator must be callable or expose generate()')
        result = await self._maybe_await(result)
        if not isinstance(result, str):
            raise TypeError('code generator returned non-string source')
        return result

    async def _start_container(self, source_path: Path) -> Any:
        start = getattr(self.container_manager, 'start', None) or getattr(self.container_manager, 'start_container', None)
        if start is None:
    async def _open_tunnel(self, container: Any) -> Any:
        port = self._extract_log_server_port(container)
        open_tunnel = getattr(self.ngrok_manager, 'open_tunnel', None) or getattr(self.ngrok_manager, 'open', None)
    async def _terminate_container(self, container: Any) -> None:
        container_id = self._extract_container_id(container)
        if await self._try_call(self.container_manager, ('send_signal', 'signal'), container_id, signal.SIGTERM):

    def _extract_log_server_port(self, container: Any) -> Any:
        for source in (self.container_manager, container):
            for attr in ('log_server_port', 'local_log_server_port', 'logs_port'):
                if hasattr(source, attr):
                    value = getattr(source, attr)
                    return value() if callable(value) else value
        if hasattr(self.container_manager, 'get_log_server_port'):
            return self.container_manager.get_log_server_port(self._extract_container_id(container))
        raise TypeError('container_manager must expose log_server_port for ngrok tunnel target')
            await self._wait_for_container(container_id, self.term_timeout)
        elif await self._try_call(self.container_manager, ('terminate', 'stop'), container_id):
            await self._wait_for_container(container_id, self.term_timeout)

        if not await self._is_container_stopped(container_id):
            await self._try_call(self.container_manager, ('send_signal', 'signal'), container_id, signal.SIGKILL)
            await self._try_call(self.container_manager, ('kill',), container_id)
            await self._wait_for_container(container_id, self.kill_timeout)

    async def _open_tunnel(self, container: Any) -> Any:
        port = self._extract_port(container)
        open_tunnel = getattr(self.ngrok_manager, 'open_tunnel', None) or getattr(self.ngrok_manager, 'open', None)
        if open_tunnel is None:
            raise TypeError('ngrok_manager must expose open_tunnel() or open()')
        return await self._maybe_await(open_tunnel(port))

    async def _close_tunnel(self, tunnel: Any) -> None:
        close = getattr(self.ngrok_manager, 'close_tunnel', None) or getattr(self.ngrok_manager, 'close', None)
        if close is not None:
            await self._maybe_await(close(tunnel))

    async def _stream_logs(self, session: RunSession) -> None:
        stream = getattr(self.container_manager, 'stream_logs', None) or getattr(self.container_manager, 'logs', None)
        if stream is None:
            return

        try:
            logs = await self._maybe_await(stream(self._extract_container_id(session.container)))
            if hasattr(logs, '__aiter__'):
                async for line in logs:
                    self.logger.info('%s', line)
            elif hasattr(logs, '__iter__') and not isinstance(logs, (str, bytes)):
                for line in logs:
                    self.logger.info('%s', line)
            elif logs:
                self.logger.info('%s', logs)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception('container log streaming failed')

    async def _wait_for_container(self, container_id: Any, timeout: float) -> None:
        wait = getattr(self.container_manager, 'wait', None) or getattr(self.container_manager, 'wait_stopped', None)
        if wait is None:
            await asyncio.sleep(0)
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._maybe_await(wait(container_id)), timeout=timeout)

    async def _is_container_stopped(self, container_id: Any) -> bool:
        is_running = getattr(self.container_manager, 'is_running', None)
        if is_running is None:
            return False
        return not bool(await self._maybe_await(is_running(container_id)))

    async def _try_call(self, obj: Any, names: tuple[str, ...], *args: Any) -> bool:
        for name in names:
            method = getattr(obj, name, None)
            if method is None:
                continue
            await self._maybe_await(method(*args))
            return True
        return False

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _extract_container_id(container: Any) -> Any:
        if isinstance(container, dict):
            return container.get('id') or container.get('container_id') or container
        return getattr(container, 'id', getattr(container, 'container_id', container))

    @staticmethod
    def _extract_port(container: Any) -> int:
        if isinstance(container, dict):
            return int(container.get('port') or container.get('host_port') or 8000)
        return int(getattr(container, 'port', getattr(container, 'host_port', 8000)))

    @staticmethod
    def _extract_public_url(tunnel: Any) -> str | None:
        if isinstance(tunnel, str):
            return tunnel
        if isinstance(tunnel, dict):
            return tunnel.get('public_url') or tunnel.get('url')
        return getattr(tunnel, 'public_url', getattr(tunnel, 'url', None))