"""Unit tests for workflow event sink and text fragmentation."""

from __future__ import annotations

import asyncio

import pytest

from lab.workflows.events import EventSink, text_fragments

_CHAT_TYPES = frozenset({"token", "thinking", "evidence_status"})


@pytest.mark.anyio
async def test_slow_consumer_blocks_producer_at_capacity_plus_one() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES, capacity=8)
    accepted_before_enqueue = 0
    producer_done = asyncio.Event()

    async def producer() -> None:
        nonlocal accepted_before_enqueue
        for index in range(20):
            accepted_before_enqueue += 1
            await sink.send({"type": "token", "text": str(index)})
        producer_done.set()

    task = asyncio.create_task(producer())
    await asyncio.sleep(0.05)
    assert accepted_before_enqueue == 9
    assert not producer_done.is_set()
    await sink.receive()
    await asyncio.sleep(0.05)
    assert accepted_before_enqueue >= 9
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_send_rejects_disallowed_event_type() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES)

    async def attempt() -> None:
        await sink.send({"type": "done", "payload": {}})

    with pytest.raises(TypeError, match="allowlist"):
        asyncio.run(attempt())


@pytest.mark.parametrize(
    ("text", "max_bytes"),
    [
        ("ascii", 8192),
        ("café résumé", 4),
        ("😀🎉", 5),
        ("中文测试", 6),
    ],
)
def test_text_fragments_unicode_concatenation_and_byte_bounds(text: str, max_bytes: int) -> None:
    parts = list(text_fragments(text, max_bytes=max_bytes))
    assert "".join(parts) == text
    for part in parts:
        assert len(part.encode("utf-8")) <= max_bytes


def test_text_fragments_empty_yields_nothing() -> None:
    assert list(text_fragments("")) == []


@pytest.mark.anyio
async def test_drain_returns_pending_without_blocking() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES, capacity=8)
    await sink.send({"type": "token", "text": "a"})
    await sink.send({"type": "token", "text": "b"})
    drained = sink.drain()
    assert drained == [{"type": "token", "text": "a"}, {"type": "token", "text": "b"}]
    assert sink.drain() == []


@pytest.mark.anyio
async def test_close_rejects_further_sends() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES)
    sink.close()
    with pytest.raises(RuntimeError, match="closed"):
        await sink.send({"type": "token", "text": "x"})
