"""Retrieval embedding prefix and format metadata coverage."""
from __future__ import annotations

import asyncio

import pytest

from lab.embedding_config import EMBEDDING_FORMAT_VERSION, format_for_embedding
from lab.retrieval import index_chunks, search


def test_index_chunks_applies_document_prefix(tmp_path):
    captured: list[list[str]] = []

    async def embedder(texts: list[str], model: str):
        captured.append(list(texts))
        return [[0.1, 0.2] for _ in texts]

    chunks = [{"chunk_id": "f:000", "file_id": "f", "file_name": "a.pdf",
               "chunk_index": 0, "text": "body", "headings": [], "pages": [1],
               "bboxes": [], "asset_ids": [], "content_hash": "abc"}]

    class Store:
        def file_path(self, topic, name):
            return tmp_path / name

    result = asyncio.run(index_chunks(
        Store(), "topic", "f", chunks,
        embedding_model="nomic-embed-text",
        embedder=embedder,
    ))
    assert result["mode"] == "hybrid"
    assert captured == [["search_document: body"]]


def test_search_applies_query_prefix(tmp_path):
    captured: list[list[str]] = []

    async def embedder(texts: list[str], model: str):
        captured.append(list(texts))
        return [[0.1, 0.2]]

    class Store:
        def file_path(self, topic, name):
            return tmp_path / "missing.sqlite"

    result = asyncio.run(search(
        Store(), "topic", "calibration",
        embedding_model="nomic-embed-text",
        embedder=embedder,
    ))
    assert captured == [["search_query: calibration"]]
    assert result["hits"] == []


def test_vectors_from_unprefixed_index_are_not_mixed(tmp_path):
    from lab.index import TopicIndex

    async def embedder(texts: list[str], model: str):
        return [[1.0, 0.0] for _ in texts]

    class Store:
        def file_path(self, topic, name):
            return tmp_path / name

    legacy = {"chunk_id": "f:000", "file_id": "f", "file_name": "a.pdf", "chunk_index": 0,
              "text": "unrelated words", "headings": [], "pages": [1], "bboxes": [],
              "asset_ids": [], "content_hash": "abc",
              "embedding": [1.0, 0.0], "embedding_model": "nomic-embed-text"}
    with TopicIndex(tmp_path / "retrieval.sqlite") as index:
        index.replace_file("f", [legacy])

    result = asyncio.run(search(Store(), "topic", "unrelated", file_ids=["f"],
                                embedding_model="nomic-embed-text", embedder=embedder))
    assert result["mode"] == "keyword"
    assert "Re-upload" in result["warning"]


def test_format_for_embedding_roles():
    assert format_for_embedding("x", "nomic-embed-text", role="document") == "search_document: x"
    assert format_for_embedding("x", "nomic-embed-text", role="query") == "search_query: x"
    assert EMBEDDING_FORMAT_VERSION == "nomic-search-prefix-v1"
