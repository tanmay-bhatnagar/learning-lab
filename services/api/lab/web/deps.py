"""Shared application dependencies for HTTP routers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from lab.config import AppConfig
from lab.contracts import FileRecord, IndexedChunk, ModelGateway, StoreProtocol
from lab.models import OllamaGateway
from lab.storage import Store

ParserFn = Callable[[bytes, str], str]
StructuredParserFn = Callable[..., tuple[dict[str, object], list[IndexedChunk]]]
RetrieverFn = Callable[..., Awaitable[dict[str, object]]]


@dataclass
class AppDeps:
    store: Store
    config: AppConfig
    model_backend: ModelGateway
    model_generation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    active_uploads: set[str] = field(default_factory=set)
    structured_parser: StructuredParserFn | None = None
    retriever: RetrieverFn | None = None
    parser_map: dict[str, ParserFn] | None = None

    def embedder(self) -> Callable[[list[str], str], Awaitable[list[list[float]]]]:
        backend = self.model_backend

        async def serialized(texts: list[str], model: str) -> list[list[float]]:
            return await backend.embed_texts(texts, model, generation_lock=self.model_generation_lock)

        return serialized
