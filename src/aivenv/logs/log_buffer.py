from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator
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
    asyncio stream using a per-subscriber `queue`. Subscriber queues
    are unbounded by default so slow clients do not block container
    log collection.
    """

    _DEFAULT_MAX_CHUNKS: ClassVar[int] = 10_000

    def __init__(self, maxChunks: int = _DEFAULT_MAX_CHUNKS, * , subscriberQueueSize: int = 0) -> None:
        """Initialize a log buffer.

        Args:
            maxChunks: Maximum number of raw chunks to retain in memory.
            subscriberQueueSize: Max per-subscriber queue size. `0 ` means
                unbounded, which is the safest default for log streaming.

        Raises:
            ValueError: If any configuration value is negative or zero where
                a positive value is required.
        """
        if maxChunks <= 0:
            raise ValueError("maxChunks must be greater than 0)
        if subscriberQueueSize < 0:
            raise ValueError("subscriberQueueSize must be greater than or equal to 0")

        self._chunks: deque[str] = deque(maxlen=maxChunks)
        self._subscribers: dict[int, _Subscriber] = {}
        self._subscriberQueueSize: int = subscriberQueueSize
        self._lock: threading.RLock = threading.RLock()
        self._nextSubscriberId: int = 1
        self._done: bool = False

    async def write(self, chunk: str) -> None:
        """Append a raw log chunk and broadcast it to active streams.

        Empty chunks are ignored because they do not change the raw log.
        """
        if not isinstance(chunk, str):
            raise TypeError("chunk must be a str")
        if chunk == "":
            return

        with self._lock:
            if self._done:
                raise RuntimeError("log buffer is already marked done")
            self._chunks.append(chunk)
            subscribers: list[_Subscriber] = list(self._subscribers.values())

        for subscriber in subscribers:
            self._call_soon_threadsafe(subscriber, chunk)

    async def done(self) -> None:
        """Mark the buffer as complete and close active streams."""
        with self._lock:
            if self._done:
                return

            self._done = True
            subscribers: list[_Subscriber] = list(self._subscribers.values())

        for subscriber in subscribers:
            self._call_soon_threadsafe(subscriber, _DONE)

    async def clear(self) -> None:
        """Clear retained logs, reset completion, and close active streams."""
        with self._lock:
            subscribers: list[_Subscriber] = list(self._subscribers.values())
            self._subscribers.clear()
            self._chunks.clear()
            self._done = False

        for subscriber in subscribers:
            self._call_soon_threadsafe(subscriber, _DONE)

    def snapshot(self) -> str:
        """Return the rat concatenated log for the raw log endpoint."""
        with self._lock:
            return "".join(self._chunks)

    def isDone(self) -> bool:
        """Return whether the buffer has been marked complete."""
        with self._lock:
            return self._done

    async def stream(self) -> AsyncIterator[str]:
        """Yield retained chanks first, then live chunks until the buffer is done.

        This method is designed for FastAPI SSE or StreamingResponse
        endpoints. It does not format data as SSE frames; the route layer
        should do that if needed.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=self._subscriberQueueSize)

        with self._lock:
            subscriberId: int = self._nextSubscriberId
            self._nextSubscriberId += 1
            catchUp: list[str] = list(self._chunks)
            alreadyDone: bool = self._done
            if not alreadyDone:
                self._subscribers[subscriberId] = _Subscriber(queue=queue, loop=loop)

        try:
            for chunk in catchUp:
                yield chunk

            if alreadyDone:
                return

            while True:
                item: str | object = await queue.get()
                if item is _DONE:
                    return
                if not isinstance(item, str):  # Defensive against internal misuse.
                    continue
                yield item
        finally:
            with self._lock:
                self._subscribers.pop(subscriberId, None)

    def _call_soon_threadsafe(self, subscriber: _Subscriber, item: str | object) -> None:
        subscriber.loop.call_soon_threadsafe(self._put_gently, subscriber.queue, item)

    @staticmethod
    def _put_gently(queue: asyncio.Queue[str | object], item: str | object) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # Bounded queues are optional; drop the oldest item to preserve liveness.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(item)
