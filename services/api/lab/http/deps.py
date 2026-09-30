"""Shared application dependencies for HTTP routers."""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass, field
from typing import Any

from lab.config import AppConfig
from lab.storage import Store


@dataclass
class AppDeps:
    store: Store
    config: AppConfig
    model_generation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    active_uploads: set[str] = field(default_factory=set)
    model_backend: Any | None = None
    structured_parser: Any | None = None
    retriever: Any | None = None
    parser_map: dict[str, Any] | None = None

    def backend(self):
        return self.model_backend or importlib.import_module("lab.models")

    def embedder(self):
        method = getattr(self.backend(), "embed_texts", None)
        if method is None or self.model_backend is not None:
            return method

        async def serialized(texts: list[str], model: str):
            return await method(texts, model, generation_lock=self.model_generation_lock)

        return serialized
