from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator
from concurrent.futures import Future
from dataclasses import dataclass
from typing import ClassVar


_DONE: object = object()


@dataclass(frozen=True)
class _Subscriber:
    """Internal record tracking a stream subscriber's queue and event loop."""

    queue: asyncio.Queue[str | object]
    loop: asyncio.AbstractEventLoop


class LogBuffer:
    """Thread-safe, asyncio-compatible in-memory log buffer.

    The buffer keeps a bounded deque of raw log chunks for snapshot
    and late-subscriber catch-up, and fans new chunks out to each active
    asyncio stream using a per-subscriber queue. Subscriber queues are
    unbounded by default so slow clients do not block log collection.
    """

    _DEFAULT_MAX_CHUNKS: ClassVar[int] = 10_000

    def __init__(self, maxChunks: int = _DEFAULT_MAX_CHUNKS, *, subscriberQueueSize: int = 0) -> None:
        """Initialize a log buffer.

        Args:
            maxChunks: Maximum number of raw chunks to retain in memory.
            subscriberQueueSize: Max per-subscriber queue size. 0 means
                unbounded, which is the safest default for log streaming.

        Raises:
            ValueError: If any configuration value is negative or zero where
                a positive value is required.
        """
        if maxChunks <= 0:
            raise ValueError("maxChunks must be greater than 0")
        if subscriberQueueSize < 0:
            raise ValueError("subscriberQueueSize must be greater than or equal to 0")

        self._chunks: deque[str] = deque(maxlen=maxChunks)
        self._subscribers: dict[int, _Subscriber] = {}
        self._subscriberQueueSize: int = subscriberQueueSize
        self._lock: threading.RLock = threading.RLock()
        self._nextSubscriberId: int = 1
        self._done: bool = False

    async def write(self, chunk: str) -> None:
        """Append a raw log chunk and broadcast it to active streams."""
        if not isinstance(chunk, str):
            raise TypeError("chunk must be a str")
        if chunk == "":
            return

        with self._lock:
            if self._done:
                raise RuntimeError("cannot write to a completed LogBuffer")
            self._chunks.append(chunk)
            subscribers = tuple(self._subscribers.items())

        await self._broadcast(subscribers, chunk)

    async def stream(self) -> AsyncIterator[str]:
        """Stream retained catch-up logs followed by future logs."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=self._subscriberQueueSize)

        with self._lock:
            catchUp = tuple(self._chunks)
            alreadyDone = self._done
            subscriberId = self._nextSubscriberId
            self._nextSubscriberId += 1
            if not alreadyDone:
                self._subscribers[subscriberId] = _Subscriber(queue=queue, loop=loop)

        try:
            for chunk in catchUp:
                yield chunk

            if alreadyDone:
                return

            while True:
                item = await queue.get()
                if item is _DONE:
                    return
                if not isinstance(item, str):
                    continue
                yield item
        finally:
            with self._lock:
                self._subscribers.pop(subscriberId, None)

    async def done(self) -> None:
        """Mark the buffer complete and close all live streams."""
        with self._lock:
            if self._done:
                return
            self._done = True
            subscribers = tuple(self._subscribers.items())
            self._subscribers.clear()

        await self._broadcast(subscribers, _DONE)

    async def clear(self) -> None:
        """Clear the retained buffer and close existing streams."""
        with self._lock:
            subscribers = tuple(self._subscribers.items())
            self._subscribers.clear()
            self._chunks.clear()
            self._done = False

        await self._broadcast(subscribers, _DONE)

    def snapshot(self) -> str:
        """Return the raw retained log text for the log endpoint."""
        with self._lock:
            return "".join(self._chunks)

    def is_done(self) -> bool:
        """Return whether the buffer has been marked complete."""
        with self._lock:
            return self._done

    async def _broadcast(self, subscribers: tupletuple[int, _Subscriber], ...], item: str | object) -> None:
        if not subscribers:
            return

        runningLoop = asyncio.get_running_loop()
        awaitables: list[Future[None] | asyncio.Future[None]] = []

        for subscriberId, subscriber in subscribers:
            if subscriber.loop.is_closed():
                with self._lock:
                    self._subscribers.pop(subscriberId, None)
                continue

            if subscriber.loop is runningLoop:
                awaitables.append(asyncio.create_task(subscriber.queue.put(item)))
            else:
                awaitables.append(asyncio.run_coroutine_threadsafe(subscriber.queue.put(item), subscriber.loop))

        for awaitable in awaitables:
            if isinstance(awaitable, asyncio.Future):
                await awaitable
            else:
                await asyncio.wrap_future(awaitable)
