from __future__ import annotations

import asyncio
import signal
from requests.exceptions import ReadTimeout

from aivenv.execution.container import ContainerManager
from aivenv.execution.container import ContainerManager


class FakeContainer:
    def __init__(self, *, log_chunks: list[bytes] | None = None, wait_timeouts: int = 0) -> None:
        self.log_chunks = log_chunks or []
        self.wait_timeouts = wait_timeouts
        self.kill_signals: list[int] = []
        self.wait_calls: list[float] = []
        self.removed = False

    def logs(self, **kwargs):
        self.log_kwargs = kwargs
        return iter(self.log_chunks)

    def kill(self, *, signal: int) -> None:
        self.kill_signals.append(signal)

    def wait(self, *, timeout: float | None = None):
        self.wait_calls.append(timeout)
        if self.wait_timeouts > 0:
            self.wait_timeouts -= 1
            raise ReadTimeout
        return {"StatusCode": 0}

    def remove(self, *, force: bool) -> None:
        self.remove_force = force
        self.removed = True


class FakeContainers:
    def __init__(self, container: FakeContainer | None = None, orphaned: list[FakeContainer] | None = None) -> None:
        self.container = container or FakeContainer()
        self.orphaned = orphaned or []
        self.run_kwargs = None
        self.list_kwargs = None

    def run(self, **kwargs):
        self.run_kwargs = kwargs
        return self.container

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return self.orphaned


class FakeClient:
    def __init__(self, containers: FakeContainers) -> None:
        self.containers = containers


class FakeLogBuffer:
    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.done_called = False

    async def write(self, chunk: str) -> None:
        self.chunks.append(chunk)

    async def done(self) -> None:
        self.done_called = True


def make_manager(containers: FakeContainers) -> ContainerManager:
    return ContainerManager(image="python:3.11-slim", cpu_limit=1.5, memory_limit="512m", client=FakeClient(containers))


def test_start_uses_locked_down_docker_options(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    output = tmp_path / "out"
    containers = FakeContainers()
    manager = make_manager(containers)

    container = manager.start(script_path=script, output_dir=output, run_id="run-123")

    assert container is containers.container
    kwargs = containers.run_kwargs
    assert kwargs["image"] == "python:3.11-slim"
    assert kwargs["command"] == ["python", "/workspace/script.py"]
    assert kwargs["detach"] is True
    assert kwargs["stdout"] is True
    assert kwargs["stderr"] is True
    assert kwargs["user"] == "1000:1000"
    assert kwargs["network_mode"] == "none"
    assert kwargs["working_dir"] == "/output"
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["nano_cpus"] == 1_500_000_000
    assert kwargs["labels"] == {"aivenv": "true", "aivenv.managed": "true", "aivenv.run_id": "run-123"}
    assert kwargs["volumes"][str(script.resolve())] == {"bind": "/workspace/script.py", "mode": "ro"}
    assert kwargs["volumes"][str(output.resolve())] == {"bind": "/output", "mode": "rw"}


def test_stream_logs_writes_decoded_chunks_and_marks_done():
    container = FakeContainer(log_chunks=[b"hello\n", "world\n".encode()])
    manager = make_manager(FakeContainers(container=container))
    log_buffer = FakeLogBuffer()

    asyncio.run(manager.stream_logs(log_buffer))

    assert log_buffer.chunks == ["hello\n", "world\n"]
    assert log_buffer.done_called is True
    assert container.log_kwargs == {"stream": True, "follow": True, "stdout": True, "stderr": True}


def test_stop_sends_sigterm_only_when_container_exits():
    container = FakeContainer()
    manager = make_manager(FakeContainers(container=container))
    manager.start(script_path=__file__, output_dir=".")

    manager.stop(timeout=3)

    assert container.kill_signals == [signal.SIGTERM]
    assert container.wait_calls == [3]
    assert manager.container is None


def test_stop_escalates_to_sigkill_after_timeout():
    container = FakeContainer(wait_timeouts=1)
    manager = make_manager(FakeContainers(container=container))
    manager.start(script_path=__file__, output_dir=".")

    manager.stop(timeout=3, kill_timeout=1)

    assert container.kill_signals == [signal.SIGTERM, signal.SIGKILL]
    assert container.wait_calls == [3, 1]


def test_cleanup_orphans_uses_aivenv_label_filters():
    orphaned = [FakeContainer(), FakeContainer()]
    containers = FakeContainers(orphaned=orphaned)
    manager = make_manager(containers)

    removed = manager.cleanup_orphans()

    assert removed == 2
    assert containers.list_kwargs == {"all": True, "filters": {"label": ["aivenv=true", "aivenv.managed=true"]}}
    assert all(container.removed for container in orphaned)
    assert all(container.remove_force is True for container in orphaned)