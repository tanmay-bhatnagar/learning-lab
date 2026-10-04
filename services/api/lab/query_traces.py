"""Pure trace-record builders and the topic-local SQLite boundary."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Literal

from lab.errors import CorruptData
from lab.storage import checked

TraceStatus = Literal["started", "completed", "rejected", "error", "cancelled"]
SCHEMA_VERSION = 1


def started_record(
    *,
    topic_id: str,
    conversation_id: str,
    message_chars: int,
    model: str,
    think: bool | str | None,
    context_limit: int,
    embedding_model: str | None,
    retrieval_top_k: int | None,
    now: str,
    trace_id: str,
) -> dict[str, object]:
    """Build a fresh trace row; request text is deliberately excluded."""
    return {
        "id": trace_id,
        "topic_id": topic_id,
        "conversation_id": conversation_id,
        "schema_version": SCHEMA_VERSION,
        "started_at": now,
        "finished_at": None,
        "status": "started",
        "query_chars": message_chars,
        "requested_model": model,
        "requested_think": think,
        "context_limit": context_limit,
        "actual_model": None,
        "embedding_model": embedding_model,
        "retrieval_top_k": retrieval_top_k,
        "selected_file_ids": [],
        "retrieved_chunks": [],
        "retained_chunks": [],
        "retrieval_mode": "none",
        "retrieval_warning": None,
        "prompt_budget": None,
        "context_used": None,
        "final_context": None,
        "cleanup_error": None,
        "preflight_ms": None,
        "retrieval_ms": None,
        "generation_ms": None,
        "first_output_ms": None,
        "total_ms": None,
        "output_chars": 0,
        "thinking_chars": 0,
        "stage": "preflight",
        "error": None,
        "user_saved": False,
        "assistant_saved": False,
        "user_message_index": None,
        "assistant_message_index": None,
    }


def retrieval_fields(
    record: dict[str, object],
    *,
    selected_file_ids: list[str],
    search_result: dict[str, object],
    retained_ids: set[str],
    citations: list[dict[str, object]],
    retrieval_ms: float,
) -> dict[str, object]:
    """Return a new trace with identifier-only retrieval and retained chunk metadata."""
    hits = search_result.get("hits", [])
    retrieved = [chunk_trace(hit, rank) for rank, hit in enumerate(hits, 1) if isinstance(hit, dict)]
    retained = [item for item in retrieved if item["chunk_id"] in retained_ids]
    warning = search_result.get("warning")
    return {
        **record,
        "selected_file_ids": list(selected_file_ids),
        "retrieved_chunks": retrieved,
        "retained_chunks": retained,
        "retrieval_mode": search_result.get("mode", "none"),
        "retrieval_warning": "degraded" if warning else None,
        "retrieval_ms": duration(retrieval_ms),
    }


def chunk_trace(hit: dict[str, object], rank: int) -> dict[str, object]:
    trace = hit.get("trace") if isinstance(hit.get("trace"), dict) else {}
    fusion = trace.get("fusion") if isinstance(trace.get("fusion"), dict) else {}
    pages = hit.get("pages", trace.get("pages", []))
    return {
        "chunk_id": hit.get("chunk_id"),
        "file_id": hit.get("file_id"),
        "page": pages[0] if isinstance(pages, list) and pages else None,
        "rank": fusion.get("rank", rank),
        "score": fusion.get("score", hit.get("score")),
    }


def duration(value: float) -> float:
    return round(max(0.0, value), 3)


def finalize_record(
    record: dict[str, object],
    *,
    status: TraceStatus,
    now: str,
    stage: str,
    total_ms: float,
    error: dict[str, str] | None = None,
    **updates: object,
) -> dict[str, object]:
    """Build final state without mutating the active record."""
    return {
        **record,
        **updates,
        "status": status,
        "finished_at": now,
        "stage": stage,
        "total_ms": duration(total_ms),
        "error": error,
    }


def trace_path(topic_path: Path) -> Path:
    return checked(topic_path / "query_traces.sqlite")


def _connect(path: Path) -> sqlite3.Connection:
    _check_database_paths(path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=5)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise CorruptData("Unsupported query trace schema version.")
        objects = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if version == 0 and objects:
            raise CorruptData("Unversioned query trace database is not compatible.")
        if version == SCHEMA_VERSION:
            _validate_v1_schema(connection, objects)
        else:
            connection.execute("""CREATE TABLE traces (
                id TEXT PRIMARY KEY NOT NULL, conversation_id TEXT NOT NULL, started_at TEXT NOT NULL,
                status TEXT NOT NULL, record_json TEXT NOT NULL
            )""")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return connection
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise CorruptData("The query trace database is corrupt; restore a backup before retrying.") from exc
    except BaseException:
        if connection is not None:
            connection.close()
        raise


def insert_started(path: Path, record: dict[str, object]) -> None:
    """Durably insert the started row in its own transaction."""
    with closing(_connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO traces VALUES (?, ?, ?, ?, ?)",
            (
                record["id"],
                record["conversation_id"],
                record["started_at"],
                "started",
                json.dumps(record, ensure_ascii=False),
            ),
        )


def finalize(path: Path, record: dict[str, object]) -> bool:
    """Finalize once, guarded by primary ID and started status."""
    with closing(_connect_existing(path)) as connection, connection:
        cursor = connection.execute(
            "UPDATE traces SET status = ?, record_json = ? WHERE id = ? AND status = 'started'",
            (record["status"], json.dumps(record, ensure_ascii=False), record["id"]),
        )
        if cursor.rowcount == 1:
            return True
        row = connection.execute("SELECT status FROM traces WHERE id = ?", (record["id"],)).fetchone()
        if row is None:
            raise CorruptData("The started query trace row is missing; restore a backup before retrying.")
        if row[0] in {"completed", "rejected", "error", "cancelled"}:
            return False
        raise CorruptData("The query trace row has an invalid status; restore a backup before retrying.")


def _connect_existing(path: Path) -> sqlite3.Connection:
    """Open an existing version 1 trace database without creating or initializing it."""
    _check_database_paths(path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=5)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        objects = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if version != SCHEMA_VERSION:
            raise CorruptData("Unsupported query trace schema version.")
        _validate_v1_schema(connection, objects)
        return connection
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise CorruptData("The query trace database is corrupt; restore a backup before retrying.") from exc
    except BaseException:
        if connection is not None:
            connection.close()
        raise


def list_traces(path: Path, *, conversation_id: str | None, limit: int) -> list[dict[str, object]]:
    """Read newest first after the route validates topic and conversation scope."""
    _check_database_paths(path)
    if not path.exists():
        return []
    uri = f"{path.as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise CorruptData("Unsupported query trace schema version.")
            objects = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            _validate_v1_schema(connection, objects)
            if conversation_id is None:
                rows = connection.execute(
                    "SELECT record_json FROM traces ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT record_json FROM traces WHERE conversation_id = ? "
                    "ORDER BY started_at DESC, id DESC LIMIT ?",
                    (conversation_id, limit),
                ).fetchall()
        records = [json.loads(row[0]) for row in rows]
    except (sqlite3.DatabaseError, ValueError, UnicodeError) as exc:
        raise CorruptData("Invalid saved query trace data; restore a backup before retrying.") from exc
    if not all(
        isinstance(record, dict)
        and record.get("schema_version") == SCHEMA_VERSION
        and record.get("status") in {"started", "completed", "rejected", "error", "cancelled"}
        for record in records
    ):
        raise CorruptData("Invalid saved query trace data; restore a backup before retrying.")
    return records


def _check_database_paths(path: Path) -> None:
    checked(path)
    for suffix in ("-journal", "-wal", "-shm"):
        checked(path.with_name(path.name + suffix))


def _validate_v1_schema(connection: sqlite3.Connection, objects: list[tuple[str]]) -> None:
    if [row[0] for row in objects] != ["traces"]:
        raise CorruptData("Invalid query trace schema; restore a backup before retrying.")
    columns = connection.execute("PRAGMA table_info(traces)").fetchall()
    expected = [
        ("id", "TEXT", 1, 1),
        ("conversation_id", "TEXT", 1, 0),
        ("started_at", "TEXT", 1, 0),
        ("status", "TEXT", 1, 0),
        ("record_json", "TEXT", 1, 0),
    ]
    actual = [(row[1], row[2].upper(), row[3], row[5]) for row in columns]
    if actual != expected:
        raise CorruptData("Invalid query trace schema; restore a backup before retrying.")


def new_trace_id() -> str:
    return str(uuid.uuid4())
