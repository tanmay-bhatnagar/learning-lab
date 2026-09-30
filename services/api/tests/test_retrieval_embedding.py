"""Retrieval embedding prefix and format metadata coverage."""

from __future__ import annotations

import asyncio

import pytest

from lab.errors import EmbeddingUnavailable
from lab.embedding_config import EMBEDDING_FORMAT_VERSION, format_for_embedding
from lab.retrieval import index_chunks, search


def test_index_chunks_applies_document_prefix(tmp_path):
    captured: list[list[str]] = []

    async def embedder(texts: list[str], model: str):
        captured.append(list(texts))
        return [[0.1, 0.2] for _ in texts]

    chunks = [
        {
            "chunk_id": "f:000",
            "file_id": "f",
            "file_name": "a.pdf",
            "chunk_index": 0,
            "text": "body",
            "headings": [],
            "pages": [1],
            "bboxes": [],
            "asset_ids": [],
            "content_hash": "abc",
        }
    ]

    class Store:
        def file_path(self, topic, name):
            return tmp_path / name

    result = asyncio.run(
        index_chunks(
            Store(),
            "topic",
            "f",
            chunks,
            embedding_model="nomic-embed-text",
            embedder=embedder,
        )
    )
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

    result = asyncio.run(
        search(
            Store(),
            "topic",
            "calibration",
            embedding_model="nomic-embed-text",
            embedder=embedder,
        )
    )
    assert captured == [["search_query: calibration"]]
    assert result["hits"] == []


def test_vectors_from_unprefixed_index_are_not_mixed(tmp_path):
    from lab.index import TopicIndex

    async def embedder(texts: list[str], model: str):
        return [[1.0, 0.0] for _ in texts]

    class Store:
        def file_path(self, topic, name):
            return tmp_path / name

    legacy = {
        "chunk_id": "f:000",
        "file_id": "f",
        "file_name": "a.pdf",
        "chunk_index": 0,
        "text": "unrelated words",
        "headings": [],
        "pages": [1],
        "bboxes": [],
        "asset_ids": [],
        "content_hash": "abc",
        "embedding": [1.0, 0.0],
        "embedding_model": "nomic-embed-text",
    }
    with TopicIndex(tmp_path / "retrieval.sqlite") as index:
        index.replace_file("f", [legacy])

    result = asyncio.run(
        search(Store(), "topic", "unrelated", file_ids=["f"], embedding_model="nomic-embed-text", embedder=embedder)
    )
    assert result["mode"] == "keyword"
    assert "Re-upload" in result["warning"]


def _chunk(text="calibration value is 42"):
    return {
        "chunk_id": "f:000",
        "file_id": "f",
        "file_name": "a.pdf",
        "chunk_index": 0,
        "text": text,
        "headings": [],
        "pages": [1],
        "bboxes": [],
        "asset_ids": [],
        "content_hash": "abc",
    }


def _store(tmp_path):
    class Store:
        def file_path(self, topic, name):
            return tmp_path / name

    return Store()


async def _unavailable(texts: list[str], model: str):
    raise EmbeddingUnavailable("Embedding model 'nomic-embed-text' is not installed locally")


async def _rejected(texts: list[str], model: str):
    raise ValueError("Embedding input exceeds the 2048-token context limit.")


def test_unavailable_embedder_still_builds_a_searchable_keyword_index(tmp_path):
    store = _store(tmp_path)
    result = asyncio.run(
        index_chunks(store, "topic", "f", [_chunk()], embedding_model="nomic-embed-text", embedder=_unavailable)
    )
    assert result["mode"] == "keyword"
    assert result["embedding_model"] == ""
    assert "not installed" in result["warning"]
    found = asyncio.run(search(store, "topic", "calibration", file_ids=["f"]))
    assert [hit["chunk_id"] for hit in found["hits"]] == ["f:000"]


def test_rejected_document_embedding_fails_loudly(tmp_path):
    with pytest.raises(ValueError, match="context limit"):
        asyncio.run(
            index_chunks(
                _store(tmp_path), "topic", "f", [_chunk()], embedding_model="nomic-embed-text", embedder=_rejected
            )
        )
    assert not (tmp_path / "retrieval.sqlite").exists()


@pytest.mark.parametrize("embedder,reason", [(_unavailable, "not installed"), (_rejected, "context limit")])
def test_query_embedding_failures_degrade_to_keyword_search(tmp_path, embedder, reason):
    store = _store(tmp_path)

    async def working(texts: list[str], model: str):
        return [[1.0, 0.0] for _ in texts]

    asyncio.run(index_chunks(store, "topic", "f", [_chunk()], embedding_model="nomic-embed-text", embedder=working))
    result = asyncio.run(
        search(store, "topic", "calibration", file_ids=["f"], embedding_model="nomic-embed-text", embedder=embedder)
    )
    assert result["mode"] == "keyword"
    assert [hit["chunk_id"] for hit in result["hits"]] == ["f:000"]
    assert reason in result["warning"]


def test_format_for_embedding_roles():
    assert format_for_embedding("x", "nomic-embed-text", role="document") == "search_document: x"
    assert format_for_embedding("x", "nomic-embed-text", role="query") == "search_query: x"
    assert EMBEDDING_FORMAT_VERSION == "nomic-search-prefix-v1"
