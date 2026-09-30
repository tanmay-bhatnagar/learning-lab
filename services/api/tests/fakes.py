"""Shared test doubles implementing the production model gateway signature."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from lab.errors import EmbeddingUnavailable


class FakeModel:
    """Minimal model gateway for HTTP-level tests.

    Omits ``embed_texts`` by default so injected backends match the previous
    no-embedding test path. Use ``EmbeddableFakeModel`` when indexing needs vectors.
    """

    def __init__(self, *, fail: bool = False, vision: bool = False, token_text: str = "answer"):
        self.calls: list[list[dict]] = []
        self.fail = fail
        self.vision = vision
        self.token_text = token_text

    async def list_models(self) -> dict:
        return {"models": [{"id": "fake", "vision": self.vision}]}

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock | None = None,
    ) -> AsyncIterator[dict]:
        self.calls.append(messages)

        async def _stream() -> AsyncIterator[dict]:
            yield {"type": "thinking", "text": "reasoning"}
            yield {"type": "token", "text": self.token_text}
            if self.fail:
                raise RuntimeError("offline")
            yield {
                "type": "done",
                "context": {
                    "used": 42,
                    "limit": context_limit,
                    "estimated": True,
                    "truncated_messages": context_metadata.get("truncated_messages", 0)
                    if context_metadata
                    else 0,
                },
                "model": model,
            }

        if generation_lock is not None:
            async with generation_lock:
                async for event in _stream():
                    yield event
        else:
            async for event in _stream():
                yield event


class EmbeddableFakeModel(FakeModel):
    """FakeModel with the production ``embed_texts`` entry point."""

    async def embed_texts(
        self,
        texts: list[str],
        model: str,
        *,
        generation_lock: asyncio.Lock | None = None,
    ) -> list[list[float]]:
        if generation_lock is not None:
            async with generation_lock:
                return [[0.1, 0.2, 0.3] for _ in texts]
        return [[0.1, 0.2, 0.3] for _ in texts]


class UnavailableEmbedFakeModel(FakeModel):
    """FakeModel whose embedder raises ``EmbeddingUnavailable`` like a missing model."""

    async def embed_texts(
        self,
        texts: list[str],
        model: str,
        *,
        generation_lock: asyncio.Lock | None = None,
    ) -> list[list[float]]:
        raise EmbeddingUnavailable("embedding disabled in test fake")


class SlowFakeModel(FakeModel):
    """Blocks in stream_chat until release is set; for concurrent-lock tests."""

    def __init__(self, started, release, **kwargs):
        super().__init__(**kwargs)
        self.started = started
        self.release = release

    async def stream_chat(self, messages, model, think, context_limit, context_metadata=None, *, generation_lock=None):
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        async for event in super().stream_chat(
            messages, model, think, context_limit, context_metadata, generation_lock=generation_lock
        ):
            yield event
