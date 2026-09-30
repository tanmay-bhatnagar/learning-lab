"""Typed internal records shared by ingestion, indexing, and retrieval."""
from __future__ import annotations

from typing import NotRequired, TypedDict


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


class ArtifactAsset(TypedDict):
    id: str
    name: str
    kind: str
    page: int | None
    bbox: dict[str, object] | None
    caption: str
    doc_ref: str


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
