"""Topic lock lifecycle for uploads and chat."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from lab.errors import Conflict


@asynccontextmanager
async def topic_lock(
    locks: dict[str, asyncio.Lock], topic: str, *, reject_if_busy: bool = False
) -> AsyncIterator[None]:
    lock = locks.setdefault(topic, asyncio.Lock())
    if reject_if_busy and lock.locked():
        raise Conflict("This topic is busy. Wait for its current upload or reply to finish.")
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()
