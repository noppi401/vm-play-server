from __future__ import annotations

import asyncio
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


class LogBuffer:
    """Thread-safe, asyncio-compatible in-memory log buffer.

    Writes are retained in a bounded deque and fanned out to
    each active subscriber through a per-subscriber asyncio.Queue.
    New subscribers first receive the currently retained backlog
    before live entries are streamed.
    """

    def __init__(self, max_lines: int = 10_000, subscriber_queue_size: int = 1000) -> None:
        if max_lines <= 0:
            raise ValueError("max_lines must be greater than zero")
        if subscriber_queue_size <= 0:
            raise ValueError("subscriber_queue_size must be greater than zero")

        self._entries: Deque[LogEntry] = deque(maxlen=max_lines)
        self._subscribers: set[asyncio.Queue[LogEntry | object]] = set()
        self._lock = asyncio.Lock()
        self._is_done = False
        self._next_sequence = 0
        self._subscriber_queue_size = subscriber_queue_size

    @property
    def is_done(self) -> bool:
        """Return whether the buffer has been marked complete."""
        return self._is_done

    async def write(self, text: str) -> None:
        """Append text to the buffer and broadcast it to live streams."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        async with self._lock:
            if self._is_done:
                raise RuntimeError("cannot write to a completed LogBuffer")
            entry = LogEntry(sequence=self._next_sequence, text=text)
            self._next_sequence += 1
            self._entries.append(entry)
            subscribers = tuple(self._subscribers)

        for queue in subscribers:
            await self._put_drop_oldest(queue, entry)

    async def stream(self, from_sequence: int | None = None) -> AsyncIterator[str]:
        """Stream retained catch-up logs followed by future logs."""
        if from_sequence is not None and from_sequence < 0:
            raise ValueError("from_sequence must be non-negative")

        queue: asyncio.Queue[LogEntry | object] = asyncio.Queue(maxsize=self._subscriber_queue_size)
        async with self._lock:
            start = 0 if from_sequence is None else from_sequence
            catch_up = tuple(entry for entry in self._entries if entry.sequence >= start)
            already_done = self._is_done
            if not already_done:
                self._subscribers.add(queue)

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
            async with self._lock:
                self._subscribers.discard(queue)

    async def done(self) -> None:
        """Mark the buffer complete and close all live streams."""
        async with self._lock:
            if self._is_done:
                return
            self._is_done = True
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()

        for queue in subscribers:
            await self._put_drop_oldest(queue, _DONE_SENTINEL)

    async def clear(self) -> None:
        """Reset the buffer and terminate existing streams."""
        async with self._lock:
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
            self._entries.clear()
            self._is_done = False
            self._next_sequence = 0

        for queue in subscribers:
            await self._put_drop_oldest(queue, _DONE_SENTINEL)

    async def snapshot(self) -> str:
        """Return the raw retained log text for the log endpoint."""
        async with self._lock:
            return "".join(entry.text for entry in self._entries)

    async def entries(self) -> tuple[LogEntry, ...]:
        """Return retained entries with sequence numbers."""
        async with self._lock:
            return tuple(self._entries)

    async def _put_drop_oldest(self, queue: asyncio.Queue[LogEntry | object], item: LogEntry | object) -> None:
        while True:
            try:
                queue.put_nowait(item)
                return
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                    queue.task_done()
