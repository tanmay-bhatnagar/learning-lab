import math
import sqlite3
from pathlib import Path

import pytest

from lab.hashing import content_hash
from lab.index import IndexInputError, TopicIndex


def _chunk(
    chunk_id: str,
    file_id: str,
    *,
    chunk_index: int,
    text: str,
    file_name: str = "paper.pdf",
    embedding: list[float] | None = None,
) -> dict:
    record = {
        "chunk_id": chunk_id,
        "file_id": file_id,
        "file_name": file_name,
        "chunk_index": chunk_index,
        "text": text,
        "headings": ["Intro"],
        "pages": [chunk_index + 1],
        "bboxes": [[0, 0, 10, 10]],
        "asset_ids": [],
        "content_hash": content_hash(text),
    }
    if embedding is not None:
        record["embedding"] = embedding
    return record


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "topics" / "quantum" / "index.sqlite"


@pytest.fixture
def index(db_path: Path) -> TopicIndex:
    topic_index = TopicIndex(db_path)
    yield topic_index
    topic_index.close()


def test_exact_term_keyword_search(index: TopicIndex) -> None:
    index.replace_file(
        "file-a",
        [
            _chunk("c1", "file-a", chunk_index=0, text="QLoRA uses 4-bit NormalFloat quantization."),
            _chunk("c2", "file-a", chunk_index=1, text="Gradient descent updates model weights."),
        ],
    )
    hits = index.keyword_search("QLoRA")
    assert [hit["chunk_id"] for hit in hits] == ["c1"]
    assert hits[0]["trace"]["keyword"]["rank"] == 1
    assert isinstance(hits[0]["trace"]["keyword"]["score"], float)


def test_read_only_open_does_not_initialize_existing_empty_database(tmp_path: Path) -> None:
    path = tmp_path / "retrieval.sqlite"
    path.touch()
    with pytest.raises(IndexInputError, match="corrupt|schema|empty"):
        TopicIndex(path, read_only=True)
    assert path.stat().st_size == 0


def test_read_only_legacy_index_keeps_keyword_retrieval_without_migrating(tmp_path: Path) -> None:
    path = tmp_path / "retrieval.sqlite"
    with TopicIndex(path) as index:
        index.replace_file("file-a", [_chunk("legacy:0", "file-a", chunk_index=0, text="quantum mechanics")])
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE chunk_embeddings DROP COLUMN model")
        connection.execute("UPDATE schema_version SET version = 1")

    with TopicIndex(path, read_only=True) as index:
        hits = index.hybrid_search("quantum", [0.1, 0.2], file_ids=["file-a"], vector_model="new-model")
        assert [hit["chunk_id"] for hit in hits] == ["legacy:0"]
        assert hits[0]["trace"]["embedding"]["rank"] is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone()[0] == 1


def test_read_only_open_rejects_index_missing_selected_file(tmp_path: Path) -> None:
    from lab.errors import CorruptData
    from lab.retrieval import search
    from lab.storage import Store

    store = Store(tmp_path / "Learning", tmp_path / "settings.json")
    topic = store.create("Index check")["id"]
    path = store.file_path(topic, "retrieval.sqlite")
    index = TopicIndex(path)
    index.replace_file("other-file", [_chunk("other:0", "other-file", chunk_index=0, text="present")])
    index.close()

    with pytest.raises(CorruptData, match="Indexed evidence is missing"):
        import asyncio

        asyncio.run(search(store, topic, "query", file_ids=["selected-file"]))


def test_fts_special_characters_do_not_break_search(index: TopicIndex) -> None:
    index.replace_file(
        "file-a",
        [_chunk("c1", "file-a", chunk_index=0, text='Use "C++" and (parens) safely.')],
    )
    assert [hit["chunk_id"] for hit in index.keyword_search('C++ (parens) OR "broken"')] == ["c1"]
    hits = index.keyword_search("C++ parens")
    assert [hit["chunk_id"] for hit in hits] == ["c1"]


def test_semantic_vector_search_with_fake_vectors(index: TopicIndex) -> None:
    index.replace_file(
        "file-a",
        [
            _chunk("c1", "file-a", chunk_index=0, text="cats and dogs", embedding=[1.0, 0.0, 0.0]),
            _chunk("c2", "file-a", chunk_index=1, text="quantum physics", embedding=[0.0, 1.0, 0.0]),
        ],
    )
    query = [0.95, 0.05, 0.0]
    hits = index.vector_search(query, limit=2)
    assert [hit["chunk_id"] for hit in hits] == ["c1", "c2"]
    assert hits[0]["trace"]["embedding"]["rank"] == 1
    assert hits[0]["trace"]["embedding"]["cosine"] > hits[1]["trace"]["embedding"]["cosine"]
    assert math.isclose(hits[0]["trace"]["embedding"]["cosine"], 0.9986, rel_tol=1e-3)


def test_hybrid_rrf_fusion(index: TopicIndex) -> None:
    index.replace_file(
        "file-a",
        [
            _chunk("kw-only", "file-a", chunk_index=0, text="exact keyword match", embedding=[0.0, 1.0]),
            _chunk("vec-only", "file-a", chunk_index=1, text="different wording", embedding=[1.0, 0.0]),
            _chunk("both", "file-a", chunk_index=2, text="exact keyword match with overlap", embedding=[1.0, 0.0]),
        ],
    )
    hits = index.hybrid_search("exact keyword", [1.0, 0.0], limit=3)
    assert len(hits) == 3
    by_id = {hit["chunk_id"]: hit for hit in hits}
    assert by_id["both"]["trace"]["keyword"]["rank"] is not None
    assert by_id["both"]["trace"]["embedding"]["rank"] is not None
    assert by_id["both"]["trace"]["fusion"]["score"] > by_id["kw-only"]["trace"]["fusion"]["score"]
    assert by_id["both"]["trace"]["fusion"]["score"] > by_id["vec-only"]["trace"]["fusion"]["score"]
    assert hits[0]["trace"]["fusion"]["rank"] == 1
    assert hits[0]["trace"]["fusion"]["score"] >= hits[1]["trace"]["fusion"]["score"]


def test_file_filtering_in_sql(index: TopicIndex) -> None:
    index.replace_file(
        "file-a",
        [_chunk("a1", "file-a", chunk_index=0, text="shared term alpha", embedding=[1.0, 0.0])],
    )
    index.replace_file(
        "file-b",
        [_chunk("b1", "file-b", chunk_index=0, text="shared term beta", embedding=[0.0, 1.0])],
    )
    assert [hit["chunk_id"] for hit in index.keyword_search("shared", file_ids=["file-a"])] == ["a1"]
    assert [hit["chunk_id"] for hit in index.vector_search([1.0, 0.0], file_ids=["file-b"])] == ["b1"]
    assert [hit["chunk_id"] for hit in index.vector_search([1.0, 0.0], file_ids=["file-a"])] == ["a1"]
    assert index.keyword_search("shared", file_ids=[]) == []
    assert index.get_chunks(file_ids=["file-b"])[0]["file_id"] == "file-b"


def test_reindex_without_duplicates(index: TopicIndex) -> None:
    first = [
        _chunk("c1", "file-a", chunk_index=0, text="first version", embedding=[1.0, 0.0]),
        _chunk("c2", "file-a", chunk_index=1, text="stable chunk", embedding=[0.0, 1.0]),
    ]
    index.replace_file("file-a", first)
    second = [
        _chunk("c1-new", "file-a", chunk_index=0, text="second version", embedding=[1.0, 0.0]),
        _chunk("c2", "file-a", chunk_index=1, text="stable chunk", embedding=[0.0, 1.0]),
    ]
    index.replace_file("file-a", second)
    chunks = index.get_chunks(file_ids=["file-a"])
    assert len(chunks) == 2
    assert [chunk["chunk_id"] for chunk in chunks] == ["c1-new", "c2"]
    assert chunks[0]["text"] == "second version"


def test_persistence_across_reopen(db_path: Path) -> None:
    with TopicIndex(db_path) as index:
        index.replace_file(
            "file-a",
            [_chunk("c1", "file-a", chunk_index=0, text="persist me", embedding=[1.0, 0.0])],
        )
    reopened = TopicIndex(db_path)
    try:
        chunks = reopened.get_chunks(chunk_ids=["c1"])
        assert chunks[0]["text"] == "persist me"
        assert chunks[0]["has_embedding"] is True
        hits = reopened.keyword_search("persist")
        assert hits[0]["chunk_id"] == "c1"
    finally:
        reopened.close()


def test_missing_embeddings_are_skipped_for_vector_search(index: TopicIndex) -> None:
    index.replace_file(
        "file-a",
        [
            _chunk("with", "file-a", chunk_index=0, text="has vector", embedding=[1.0, 0.0]),
            _chunk("without", "file-a", chunk_index=1, text="no vector"),
        ],
    )
    hits = index.vector_search([1.0, 0.0])
    assert [hit["chunk_id"] for hit in hits] == ["with"]
    hybrid = index.hybrid_search("vector", [1.0, 0.0], limit=2)
    assert {hit["chunk_id"] for hit in hybrid} == {"with", "without"}


def test_malformed_embedding_dimensions(index: TopicIndex) -> None:
    with pytest.raises(IndexInputError, match="same dimension"):
        index.replace_file(
            "file-a",
            [
                _chunk("c1", "file-a", chunk_index=0, text="one", embedding=[1.0, 0.0]),
                _chunk("c2", "file-a", chunk_index=1, text="two", embedding=[1.0]),
            ],
        )
    index.replace_file(
        "file-a",
        [_chunk("c1", "file-a", chunk_index=0, text="stored", embedding=[1.0, 0.0])],
    )
    with pytest.raises(IndexInputError, match="dimension"):
        index.vector_search([1.0, 0.0, 0.0])


def test_remove_file(index: TopicIndex) -> None:
    index.replace_file("file-a", [_chunk("c1", "file-a", chunk_index=0, text="remove me")])
    assert index.remove_file("file-a") == 1
    assert index.get_chunks(file_ids=["file-a"]) == []


def test_get_chunks_filters(index: TopicIndex) -> None:
    index.replace_file("file-a", [_chunk("c1", "file-a", chunk_index=0, text="one")])
    index.replace_file("file-b", [_chunk("c2", "file-b", chunk_index=0, text="two")])
    assert [chunk["chunk_id"] for chunk in index.get_chunks(chunk_ids=["c2"])] == ["c2"]
