"""Topic-scoped SQLite FTS5 + optional embedding index (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
DEFAULT_RRF_K = 60
_FTS_TOKEN = re.compile(r"[\w]+", re.UNICODE)


class IndexInputError(ValueError):
    """Raised when chunk or search inputs are invalid."""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_loads(raw: str, default: Any) -> Any:
    if raw in (None, ""):
        return default
    return json.loads(raw)


def _fts_query(raw: str) -> str | None:
    """Build a safe FTS5 MATCH expression; return None when no searchable tokens."""
    tokens = _FTS_TOKEN.findall(raw)
    if not tokens:
        return None
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _pack_vector(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def _unpack_vector(blob: bytes, dimension: int) -> list[float]:
    expected = dimension * struct.calcsize("f")
    if len(blob) != expected:
        raise IndexInputError(f"Stored vector length {len(blob)} does not match dimension {dimension}")
    return list(struct.unpack(f"{dimension}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise IndexInputError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for left, right in zip(a, b, strict=True):
        dot += left * right
        norm_a += left * left
        norm_b += right * right
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def _chunk_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "chunk_id": row["chunk_id"],
        "file_id": row["file_id"],
        "file_name": row["file_name"],
        "chunk_index": row["chunk_index"],
        "text": row["text"],
        "headings": _json_loads(row["headings_json"], []),
        "pages": _json_loads(row["pages_json"], []),
        "bboxes": _json_loads(row["bboxes_json"], []),
        "asset_ids": _json_loads(row["asset_ids_json"], []),
        "content_hash": row["content_hash"],
        "has_embedding": bool(row["has_embedding"]),
        "embedding_model": row["embedding_model"] if "embedding_model" in row.keys() else "",
    }


def _trace_component(rank: int | None, score: float | None, *, cosine: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"rank": rank, "score": score}
    if cosine is not None:
        payload["cosine"] = cosine
    return payload


def _validate_file_ids(file_ids: list[str] | None) -> list[str] | None:
    if file_ids is None:
        return None
    if not isinstance(file_ids, list) or any(not isinstance(item, str) or not item for item in file_ids):
        raise IndexInputError("file_ids must be a list of non-empty strings")
    return sorted(dict.fromkeys(file_ids))


def _validate_chunk_record(record: dict[str, Any], expected_file_id: str | None = None) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise IndexInputError("Each chunk record must be a JSON object")
    required = ("chunk_id", "file_id", "file_name", "chunk_index", "text", "content_hash")
    missing = [field for field in required if field not in record]
    if missing:
        raise IndexInputError(f"Chunk record missing required fields: {', '.join(missing)}")
    file_id = record["file_id"]
    if expected_file_id is not None and file_id != expected_file_id:
        raise IndexInputError("All chunk records must share the replace_file file_id")
    if not isinstance(record["chunk_index"], int) or record["chunk_index"] < 0:
        raise IndexInputError("chunk_index must be a non-negative integer")
    if not isinstance(record["text"], str):
        raise IndexInputError("text must be a string")
    normalized = {
        "chunk_id": str(record["chunk_id"]),
        "file_id": str(file_id),
        "file_name": str(record["file_name"]),
        "chunk_index": record["chunk_index"],
        "text": record["text"],
        "headings": record.get("headings", []),
        "pages": record.get("pages", []),
        "bboxes": record.get("bboxes", []),
        "asset_ids": record.get("asset_ids", []),
        "content_hash": str(record["content_hash"]),
        "embedding": record.get("embedding"),
        "embedding_model": str(record.get("embedding_model", "")),
    }
    for field in ("headings", "pages", "bboxes", "asset_ids"):
        if not isinstance(normalized[field], list):
            raise IndexInputError(f"{field} must be a list")
    embedding = normalized["embedding"]
    if embedding is not None:
        if not isinstance(embedding, list) or not embedding:
            raise IndexInputError("embedding must be a non-empty list of floats")
        if any(not isinstance(value, (int, float)) for value in embedding):
            raise IndexInputError("embedding must contain only numbers")
        normalized["embedding"] = [float(value) for value in embedding]
    return normalized


def _fuse_ranked_hits(
    keyword_hits: list[dict[str, Any]], vector_hits: list[dict[str, Any]], limit: int, rrf_k: int
) -> list[dict[str, Any]]:
    """Combine ranked result records deterministically without touching the index."""
    keyword_by_id = {hit["chunk_id"]: hit for hit in keyword_hits}
    vector_by_id = {hit["chunk_id"]: hit for hit in vector_hits}
    scores: list[tuple[float, str]] = []
    for chunk_id in sorted(set(keyword_by_id) | set(vector_by_id)):
        keyword_rank = keyword_by_id.get(chunk_id, {}).get("trace", {}).get("keyword", {}).get("rank")
        vector_rank = vector_by_id.get(chunk_id, {}).get("trace", {}).get("embedding", {}).get("rank")
        score = 1.0 / (rrf_k + keyword_rank) if keyword_rank is not None else 0.0
        score += 1.0 / (rrf_k + vector_rank) if vector_rank is not None else 0.0
        scores.append((score, chunk_id))
    scores.sort(key=lambda item: (-item[0], item[1]))
    results: list[dict[str, Any]] = []
    for rank, (score, chunk_id) in enumerate(scores[:limit], start=1):
        source = keyword_by_id.get(chunk_id) or vector_by_id[chunk_id]
        payload = {key: value for key, value in source.items() if key != "trace"}
        empty = {"keyword": _trace_component(None, None), "embedding": _trace_component(None, None)}
        keyword_trace = keyword_by_id.get(chunk_id, {"trace": empty})["trace"]["keyword"]
        embedding_trace = vector_by_id.get(chunk_id, {"trace": empty})["trace"]["embedding"]
        payload["trace"] = {
            "keyword": keyword_trace,
            "embedding": embedding_trace,
            "fusion": _trace_component(rank, score),
        }
        results.append(payload)
    return results


class TopicIndex:
    """Per-topic search index backed by SQLite FTS5 and optional embeddings."""

    def __init__(self, db_path: str | Path, *, read_only: bool = False):
        self.db_path = Path(db_path)
        self._schema_version = SCHEMA_VERSION
        if read_only and not self.db_path.is_file():
            raise IndexInputError(f"Retrieval index is missing: {self.db_path}")
        if not read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        database = f"{self.db_path.resolve().as_uri()}?mode=ro" if read_only else str(self.db_path)
        try:
            self._conn = sqlite3.connect(database, timeout=5.0, uri=read_only)
        except sqlite3.DatabaseError as exc:
            raise IndexInputError(f"Retrieval index is corrupt: {self.db_path}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if not read_only:
            self._conn.execute("PRAGMA journal_mode = WAL")
        if read_only:
            try:
                self._validate_existing_schema()
            except (sqlite3.DatabaseError, IndexInputError) as exc:
                self._conn.close()
                if isinstance(exc, sqlite3.DatabaseError):
                    raise IndexInputError(f"Retrieval index is corrupt: {self.db_path}") from exc
                raise
        else:
            self._ensure_schema()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TopicIndex:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        current = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if current is None:
            self._create_schema_v1()
            self._conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()
            return
        version = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if version is None:
            raise IndexInputError("schema_version table exists but has no version row")
        if version["version"] == 1:
            with self._conn:
                self._conn.execute("ALTER TABLE chunk_embeddings ADD COLUMN model TEXT NOT NULL DEFAULT ''")
                self._conn.execute("UPDATE schema_version SET version = 2")
            return
        if version["version"] != SCHEMA_VERSION:
            raise IndexInputError(f"Unsupported schema version {version['version']}; expected {SCHEMA_VERSION}")

    def _validate_existing_schema(self) -> None:
        current = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if current is None:
            raise IndexInputError("Retrieval index has no schema_version table")
        version = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if version is None or version["version"] not in (1, SCHEMA_VERSION):
            raise IndexInputError("Retrieval index has an unsupported or empty schema version")
        self._schema_version = version["version"]
        required = {"chunks", "chunks_fts", "chunk_embeddings"}
        present = {
            row["name"] for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        }
        if not required.issubset(present):
            raise IndexInputError("Retrieval index is missing required tables")
        required_columns = {
            "chunks": {
                "chunk_id",
                "file_id",
                "file_name",
                "chunk_index",
                "text",
                "headings_json",
                "pages_json",
                "bboxes_json",
                "asset_ids_json",
                "content_hash",
                "has_embedding",
            },
            "chunk_embeddings": {"chunk_id", "dimension", "vector"},
        }
        for table, expected in required_columns.items():
            actual = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if not expected.issubset(actual):
                raise IndexInputError(f"Retrieval index table {table} is incomplete")
        self._conn.execute("SELECT text FROM chunks_fts LIMIT 0")

    def _create_schema_v1(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE schema_version (
                version INTEGER NOT NULL
            );

            CREATE TABLE chunks (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                file_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                headings_json TEXT NOT NULL DEFAULT '[]',
                pages_json TEXT NOT NULL DEFAULT '[]',
                bboxes_json TEXT NOT NULL DEFAULT '[]',
                asset_ids_json TEXT NOT NULL DEFAULT '[]',
                content_hash TEXT NOT NULL,
                has_embedding INTEGER NOT NULL DEFAULT 0,
                UNIQUE(file_id, chunk_index)
            );

            CREATE INDEX idx_chunks_file_id ON chunks(file_id);

            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                text,
                content='chunks',
                content_rowid='rowid',
                tokenize='unicode61'
            );

            CREATE TABLE chunk_embeddings (
                chunk_id TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                vector BLOB NOT NULL,
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
            );

            CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
            END;

            CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
            END;

            CREATE TRIGGER chunks_au AFTER UPDATE OF text ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
                INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
            END;
            """
        )

    def replace_file(self, file_id: str, chunks: list[dict[str, Any]]) -> dict[str, int]:
        if not isinstance(file_id, str) or not file_id:
            raise IndexInputError("file_id must be a non-empty string")
        if not isinstance(chunks, list):
            raise IndexInputError("chunks must be a list of JSON chunk records")

        normalized = [_validate_chunk_record(record, file_id) for record in chunks]
        chunk_ids = [record["chunk_id"] for record in normalized]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise IndexInputError("chunk_id values must be unique within replace_file")

        expected_dim: int | None = None
        for record in normalized:
            embedding = record["embedding"]
            if embedding is None:
                continue
            dim = len(embedding)
            if expected_dim is None:
                expected_dim = dim
            elif dim != expected_dim:
                raise IndexInputError("All embeddings in replace_file must share the same dimension")

        with self._conn:
            self._conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
            inserted = 0
            embedded = 0
            for record in normalized:
                self._conn.execute(
                    """
                    INSERT INTO chunks(
                        chunk_id, file_id, file_name, chunk_index, text,
                        headings_json, pages_json, bboxes_json, asset_ids_json,
                        content_hash, has_embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["chunk_id"],
                        record["file_id"],
                        record["file_name"],
                        record["chunk_index"],
                        record["text"],
                        _json_dumps(record["headings"]),
                        _json_dumps(record["pages"]),
                        _json_dumps(record["bboxes"]),
                        _json_dumps(record["asset_ids"]),
                        record["content_hash"],
                        1 if record["embedding"] is not None else 0,
                    ),
                )
                inserted += 1
                embedding = record["embedding"]
                if embedding is not None:
                    self._conn.execute(
                        """
                        INSERT INTO chunk_embeddings(chunk_id, model, dimension, vector)
                        VALUES (?, ?, ?, ?)
                        """,
                        (record["chunk_id"], record["embedding_model"], len(embedding), _pack_vector(embedding)),
                    )
                    embedded += 1
        return {"inserted": inserted, "embedded": embedded, "file_id": file_id}

    def remove_file(self, file_id: str) -> int:
        if not isinstance(file_id, str) or not file_id:
            raise IndexInputError("file_id must be a non-empty string")
        with self._conn:
            cursor = self._conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        return cursor.rowcount

    def get_chunks(
        self,
        *,
        chunk_ids: list[str] | None = None,
        file_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if chunk_ids is not None and (not isinstance(chunk_ids, list) or not chunk_ids):
            raise IndexInputError("chunk_ids must be a non-empty list when provided")
        file_ids = _validate_file_ids(file_ids)

        clauses: list[str] = []
        params: list[Any] = []
        if chunk_ids is not None:
            placeholders = ",".join("?" for _ in chunk_ids)
            clauses.append(f"chunk_id IN ({placeholders})")
            params.extend(chunk_ids)
        if file_ids is not None:
            placeholders = ",".join("?" for _ in file_ids)
            clauses.append(f"file_id IN ({placeholders})")
            params.extend(file_ids)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT chunk_id, file_id, file_name, chunk_index, text,
                   headings_json, pages_json, bboxes_json, asset_ids_json,
                   content_hash, has_embedding, '' AS embedding_model
            FROM chunks
            {where}
            ORDER BY file_id ASC, chunk_index ASC, chunk_id ASC
            """,
            params,
        ).fetchall()
        return [_chunk_row_to_dict(row) for row in rows]

    def keyword_search(
        self,
        query: str,
        *,
        file_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str):
            raise IndexInputError("query must be a string")
        if limit <= 0:
            return []
        file_ids = _validate_file_ids(file_ids)
        if file_ids == []:
            return []

        match = _fts_query(query)
        if match is None:
            return []

        params: list[Any] = [match]
        filter_clause = ""
        if file_ids is not None:
            placeholders = ",".join("?" for _ in file_ids)
            filter_clause = f"AND c.file_id IN ({placeholders})"
            params.extend(file_ids)
        params.append(limit)

        rows = self._conn.execute(
            f"""
            SELECT c.chunk_id, c.file_id, c.file_name, c.chunk_index, c.text,
                   c.headings_json, c.pages_json, c.bboxes_json, c.asset_ids_json,
                   c.content_hash, c.has_embedding, '' AS embedding_model,
                   bm25(chunks_fts) AS keyword_score
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            {filter_clause}
            ORDER BY keyword_score ASC, c.chunk_id ASC
            LIMIT ?
            """,
            params,
        ).fetchall()

        results: list[dict[str, Any]] = []
        for rank, row in enumerate(rows, start=1):
            payload = _chunk_row_to_dict(row)
            payload["trace"] = {
                "keyword": _trace_component(rank, float(row["keyword_score"])),
                "embedding": _trace_component(None, None, cosine=None),
                "fusion": _trace_component(None, None),
            }
            results.append(payload)
        return results

    def vector_search(
        self,
        vector: list[float],
        *,
        file_ids: list[str] | None = None,
        limit: int = 10,
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(vector, list) or not vector:
            raise IndexInputError("vector must be a non-empty list of floats")
        if any(not isinstance(value, (int, float)) for value in vector):
            raise IndexInputError("vector must contain only numbers")
        query_vector = [float(value) for value in vector]
        if limit <= 0:
            return []
        file_ids = _validate_file_ids(file_ids)
        if file_ids == []:
            return []
        if self._schema_version == 1:
            return []

        params: list[Any] = []
        filter_clause = ""
        if file_ids is not None:
            placeholders = ",".join("?" for _ in file_ids)
            filter_clause = f"AND c.file_id IN ({placeholders})"
            params.extend(file_ids)
        if model is not None:
            filter_clause += " AND e.model = ?"
            params.append(model)

        rows = self._conn.execute(
            f"""
            SELECT c.chunk_id, c.file_id, c.file_name, c.chunk_index, c.text,
                   c.headings_json, c.pages_json, c.bboxes_json, c.asset_ids_json,
                   c.content_hash, c.has_embedding, e.model AS embedding_model,
                   e.dimension, e.vector
            FROM chunks c
            JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
            WHERE c.has_embedding = 1
            {filter_clause}
            ORDER BY c.chunk_id ASC
            """,
            params,
        ).fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            if row["dimension"] != len(query_vector):
                raise IndexInputError(
                    f"Query vector dimension {len(query_vector)} does not match stored dimension {row['dimension']}"
                )
            cosine = _cosine(query_vector, _unpack_vector(row["vector"], row["dimension"]))
            scored.append((cosine, row))

        scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        results: list[dict[str, Any]] = []
        for rank, (cosine, row) in enumerate(scored[:limit], start=1):
            payload = _chunk_row_to_dict(row)
            payload["trace"] = {
                "keyword": _trace_component(None, None),
                "embedding": _trace_component(rank, cosine, cosine=cosine),
                "fusion": _trace_component(None, None),
            }
            results.append(payload)
        return results

    def hybrid_search(
        self,
        query: str,
        vector: list[float] | None = None,
        *,
        file_ids: list[str] | None = None,
        limit: int = 10,
        rrf_k: int = DEFAULT_RRF_K,
        vector_model: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if rrf_k <= 0:
            raise IndexInputError("rrf_k must be positive")

        keyword_hits = self.keyword_search(query, file_ids=file_ids, limit=max(limit * 5, limit))
        vector_hits: list[dict[str, Any]] = []
        if vector is not None:
            vector_hits = self.vector_search(
                vector,
                file_ids=file_ids,
                limit=max(limit * 5, limit),
                model=vector_model,
            )

        return _fuse_ranked_hits(keyword_hits, vector_hits, limit, rrf_k)
