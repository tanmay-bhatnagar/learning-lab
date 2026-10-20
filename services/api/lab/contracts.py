"""Typed internal records shared by ingestion, indexing, and retrieval."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, NotRequired, Protocol, TypedDict


FileStatus = Literal["processing", "ready", "error"]
IndexStatus = Literal["ready", "error", "not_indexed"]
IndexMode = Literal["hybrid", "keyword", "none"]


class ExtractionDiagnostics(TypedDict):
    status: str
    note: NotRequired[str]
    findings: list[str]


class FileRecord(TypedDict, total=False):
    id: str
    name: str
    original_name: str
    status: FileStatus
    parser: str
    markdown_name: str
    docling_name: str
    chunks_name: str
    parse_name: str
    index_status: IndexStatus
    index_mode: IndexMode
    embedding_model: str
    error: str
    interrupted: bool
    warnings: list[str]
    extraction_diagnostics: ExtractionDiagnostics
    assets: list[dict[str, object]]
    content_sha256: str
    parser_version: str
    page_count: int
    asset_count: int


class TopicRecord(TypedDict, total=False):
    id: str
    name: str
    learning_goal: str
    archived: bool


class Message(TypedDict, total=False):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    thinking: str
    model: str
    file_ids: list[str]
    incomplete: bool
    retrieval: dict[str, object]
    summary_import: dict[str, object]
    prerequisite_import: dict[str, object]


class Session(TypedDict, total=False):
    messages: list[Message]
    context: dict[str, object]


class IndexedChunk(TypedDict):
    chunk_id: str
    file_id: str
    file_name: str
    chunk_index: int
    text: str
    headings: list[str]
    pages: list[int]
    bboxes: list[dict[str, object]]
    asset_ids: list[str]
    content_hash: str
    embedding: NotRequired[list[float] | None]
    embedding_model: NotRequired[str]
    has_embedding: NotRequired[bool]
    trace: NotRequired[dict[str, object]]


class ChunkRecord(TypedDict):
    index: NotRequired[int]
    text: str
    contextualized_text: str
    headings: list[str]
    pages: list[int]
    bboxes: list[dict[str, object]]
    picture_asset_ids: list[str]
    split_for_embedding: NotRequired[bool]


class Citation(TypedDict):
    chunk_id: str
    file_id: str
    file_name: str
    headings: list[str]
    pages: list[int]
    bboxes: list[dict[str, object]]
    assets: list[str]
    trace: dict[str, object]
    text: str
    chunk_index: NotRequired[int]
    source_label: NotRequired[str]


class ArtifactAsset(TypedDict):
    id: str
    name: str
    kind: str
    page: int | None
    bbox: dict[str, object] | None
    caption: str | None
    doc_ref: str | None


class ParseUpdates(TypedDict):
    markdown_name: str
    docling_name: str
    chunks_name: str
    parse_name: str
    content_sha256: str
    parser_version: str
    page_count: int
    asset_count: int
    assets: list[ArtifactAsset]
    warnings: list[str]
    extraction_diagnostics: ExtractionDiagnostics


class ChatPromptPlan(TypedDict):
    prompt: list[dict[str, object]]
    prompt_context: dict[str, object]
    retained_indices: tuple[int, ...]
    citations: list[Citation]
    retrieval_record: dict[str, object]


ChatStreamEvent = dict[str, object]


class CloseableAsyncStream(Protocol):
    """Model chat streams are async generators with ``aclose`` (Ollama gateway and test fakes)."""

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]: ...

    async def aclose(self) -> None: ...


class TopicSettings(Protocol):
    """Topic retrieval settings loaded outside workflows (concrete type lives in ``lab.web.schemas``)."""

    embedding_model: str
    retrieval_top_k: int


class ModelGateway(Protocol):
    async def list_models(self) -> dict[str, object]: ...

    async def embed_texts(
        self,
        texts: list[str],
        model: str,
        *,
        generation_lock: asyncio.Lock,
    ) -> list[list[float]]: ...

    def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock,
        response_schema: dict | None = None,
    ) -> CloseableAsyncStream: ...


class StoreProtocol(Protocol):
    root: Path
    settings: Path

    def topic(self, topic: str) -> Path: ...

    def topics(self) -> list[dict[str, str]]: ...

    def create(self, name: str) -> dict[str, str]: ...

    def files(self, topic: str) -> list[FileRecord]: ...

    def file(self, topic: str, file_id: str) -> FileRecord: ...

    def file_path(self, topic: str, name: str) -> Path: ...

    def conversations(self, topic: str) -> list[dict[str, str]]: ...

    def conversation(self, topic: str, conversation_id: str) -> dict[str, str]: ...

    def session(self, topic: str, conversation_id: str = "default") -> Session: ...

    def save_session(self, topic: str, session: Session, conversation_id: str = "default") -> None: ...
