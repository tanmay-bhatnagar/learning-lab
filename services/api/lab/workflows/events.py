"""Bounded workflow event channel and UTF-8 text fragmentation."""

from __future__ import annotations

import asyncio
from collections.abc import Generator, Mapping


class EventSink:
    """Asyncio queue wrapper with family-specific event type allowlisting."""

    def __init__(
        self,
        *,
        allowed_types: frozenset[str],
        capacity: int = 8,
    ) -> None:
        self._allowed = allowed_types
        self._queue: asyncio.Queue[Mapping[str, object]] = asyncio.Queue(maxsize=capacity)
        self._closed = False

    async def send(self, event: Mapping[str, object]) -> None:
        """Enqueue an event; block when the queue is full until space is available."""
        if self._closed:
            msg = "EventSink is closed"
            raise RuntimeError(msg)
        event_type = event.get("type")
        if not isinstance(event_type, str) or event_type not in self._allowed:
            msg = f"event type {event_type!r} is not in the family allowlist"
            raise TypeError(msg)
        await self._queue.put(event)

    async def receive(self) -> Mapping[str, object]:
        """Wait for the next queued event."""
        return await self._queue.get()

    def drain(self) -> list[Mapping[str, object]]:
        """Return all currently queued events without blocking."""
        drained: list[Mapping[str, object]] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return drained

    def close(self) -> None:
        """Reject further sends."""
        self._closed = True


def text_fragments(text: str, max_bytes: int = 8192) -> Generator[str, None, None]:
    """Yield successive UTF-8 slices of ``text`` without splitting code points."""
    if not text:
        return
    buffer: list[str] = []
    buffer_bytes = 0
    for character in text:
        character_bytes = len(character.encode("utf-8"))
        if buffer and buffer_bytes + character_bytes > max_bytes:
            yield "".join(buffer)
            buffer = [character]
            buffer_bytes = character_bytes
        else:
            buffer.append(character)
            buffer_bytes += character_bytes
    if buffer:
        yield "".join(buffer)
