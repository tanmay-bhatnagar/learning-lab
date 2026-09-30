"""Topic lock lifecycle for uploads and chat."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from lab.errors import Conflict


class TopicLockLease:
    """Idempotent release for streaming hand-offs (D5)."""

    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._released = False
        self._handed_off = False

    def hand_off(self) -> None:
        """Keep the lock held after the acquiring context exits."""
        self._handed_off = True

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._lock.release()

    @property
    def handed_off(self) -> bool:
        return self._handed_off


def topic_lock_busy(locks: dict[str, asyncio.Lock], topic: str) -> bool:
    return locks.setdefault(topic, asyncio.Lock()).locked()


async def acquire_topic_lock(
    locks: dict[str, asyncio.Lock],
    topic: str,
    *,
    reject_if_busy: bool = False,
) -> TopicLockLease:
    lock = locks.setdefault(topic, asyncio.Lock())
    if reject_if_busy and lock.locked():
        raise Conflict("This topic is busy. Wait for its current upload or reply to finish.")
    await lock.acquire()
    return TopicLockLease(lock)


@asynccontextmanager
async def topic_lock(
    locks: dict[str, asyncio.Lock],
    topic: str,
    *,
    reject_if_busy: bool = False,
) -> AsyncIterator[TopicLockLease]:
    lease = await acquire_topic_lock(locks, topic, reject_if_busy=reject_if_busy)
    try:
        yield lease
    finally:
        if not lease.handed_off:
            lease.release()
