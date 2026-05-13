from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Deque, Final


_DONE_SENTINEL: Final[object] = object()


@dataclass(frozen=True, slots=True)
class LogEntry:
    """A single retained log entry."""

    sequence: int
    text: str


@dataclass(frozen=True, slots=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[LogEntry | object]


class LogBuffer:
    """Thread-safe, asyncio-compatible in-memory log buffer."""

    def __init__(self, max_lines: int = 10_000, subscriber_queue_size: int = 1000) -> None:
        if max_lines <= 0:
            raise ValueError("max_lines must be greater than zero")
        if subscriber_queue_size <= 0:
            raise ValueError("subscriber_queue_size must be greater than zero")

        self._entries: Deque[LogEntry] = deque(maxlen=max_lines)
        self._subscribers: set[_Subscriber] = set()
        self._lock = threading.RLock()
        self._is_done = False
        self._next_sequence = 0
        self._subscriber_queue_size = subscriber_queue_size

    @property
    def is_done(self) -> bool:
        with self._lock:
            return self._is_done

    async def write(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        with self._lock:
            if self._is_done:
                raise RuntimeError("cannot write to a completed LogBuffer")
            entry = LogEntry(sequence=self._next_sequence, text=text)
            self._next_sequence += 1
            self._entries.append(entry)
            subscribers = tuple(self._subscribers)

        await self._broadcast(subscribers, entry)

    async def stream(self, from_sequence: int | None = None) -> AsyncIterator[str]:
        if from_sequence is not None and from_sequence < 0:
            raise ValueError("from_sequence must be non-negative")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[LogEntry | object] = asyncio.Queue(maxsize=self._subscriber_queue_size)
        subscriber = _Subscriber(loop=loop, queue=queue)

        with self._lock:
            start = 0 if from_sequence is None else from_sequence
            catch_up = tuple(entry for entry in self._entries if entry.sequence >= start)
            already_done = self._is_done
            if not already_done:
                self._subscribers.add(subscriber)

        try:
            for entry in catch_up:
                yield entry.text
            if already_done:
                return

            while True:
                item = await queue.get()
                if item is _DONE_SENTINEL:
                    return
                if isinstance(item, LogEntry):
                    yield item.text
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)

    async def done(self) -> None:
        with self._lock:
            if self._is_done:
                return
            self._is_done = True
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()

        await self._broadcast(subscribers, _DONE_SENTINEL)

    async def clear(self) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
            self._entries.clear()
            self._is_done = False
            self._next_sequence = 0

        await self._broadcast(subscribers, _DONE_SENTINEL)

    async def snapshot(self) -> str:
        with self._lock:
            return "".join(entry.text for entry in self._entries)

    async def entries(self) -> tuple[LogEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    async def _broadcast(self, subscribers: tuple[_Subscriber, ...], item: LogEntry | object) -> None:
        if not subscribers:
            return
        running_loop = asyncio.get_running_loop()
        futures: list[asyncio.Future[None]] = []

        for subscriber in subscribers:
            if subscriber.loop.is_closed():
                with self._lock:
                    self._subscribers.discard(subscriber)
                continue

            if subscriber.loop is running_loop:
                self._put_nowait(subscriber.queue, item)
                continue

            future = asyncio.run_coroutine_threadsafe(
                self._put_from_foreign_loop(subscriber.queue, item),
                subscriber.loop,
            )
            futures.append(asyncio.wrap_future(future))

        if futures:
            await asyncio.gather(*futures)

    @staticmethod
    async def _put_from_foreign_loop(queue: asyncio.Queue[LogEntry | object], item: LogEntry | object) -> None:
        LogBuffer._put_nowait(queue, item)

    @staticmethod
    def _put_nowait(queue: asyncio.Queue[LogEntry | object], item: LogEntry | object) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            queue.put_nowait(item)
