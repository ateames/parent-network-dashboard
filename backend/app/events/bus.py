"""In-process pub/sub for live stream events (single-Pi, no broker)."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.events.ordering import sort_stream_events

if TYPE_CHECKING:
    from app.schemas.events import StreamEventOut

DEFAULT_RECENT_CAPACITY = 500


class EventBus:
    """Fan-out published events to SSE subscribers; keep a recent ring buffer."""

    def __init__(self, *, capacity: int = DEFAULT_RECENT_CAPACITY) -> None:
        self._capacity = max(1, capacity)
        self._recent: deque[StreamEventOut] = deque(maxlen=self._capacity)
        self._subscribers: set[asyncio.Queue[StreamEventOut]] = set()
        self._seen_ids: set = set()

    def publish(self, event: StreamEventOut) -> bool:
        """Publish ``event`` to subscribers and the recent buffer.

        Returns False if this event id was already published (dedupe).
        """
        if event.id in self._seen_ids:
            return False
        self._seen_ids.add(event.id)
        # Bound seen-id memory roughly with the ring buffer.
        if len(self._seen_ids) > self._capacity * 2:
            keep = {e.id for e in self._recent}
            keep.add(event.id)
            self._seen_ids = keep
        self._recent.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow subscriber: drop oldest queued item, then retry once.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass
        return True

    def recent(self, limit: int = 50) -> list[StreamEventOut]:
        """Return up to ``limit`` events ordered by severity, then time."""
        return sort_stream_events(list(self._recent), limit=limit)

    def subscribe(self, *, maxsize: int = 256) -> asyncio.Queue[StreamEventOut]:
        queue: asyncio.Queue[StreamEventOut] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[StreamEventOut]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def listen(self) -> AsyncIterator[StreamEventOut]:
        """Async iterator of events until the subscriber cancels."""
        queue = self.subscribe()
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(queue)

    def clear(self) -> None:
        """Reset buffer and subscribers (tests)."""
        self._recent.clear()
        self._seen_ids.clear()
        self._subscribers.clear()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_event_bus() -> EventBus:
    """Replace the process-wide bus (used by tests)."""
    global _bus
    _bus = EventBus()
    return _bus
