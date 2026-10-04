"""Run a real-parser, production-retrieval evaluation with simulated generation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from evals.retrieval.manifest import LoadedManifest, load_manifest
from evals.retrieval.scorer import score_case


SIMULATED_THINKING = "Simulated generation; answer quality is not evaluated."
SIMULATED_ANSWER = "Simulated answer; answer quality is not evaluated."


class SimulatedGateway:
    """Test gateway that records the production prompt and never evaluates answers."""

    def __init__(self, embed_gateway: Any = None) -> None:
        self.prompts: list[list[dict[str, Any]]] = []
        self.embed_gateway = embed_gateway

    async def list_models(self) -> dict[str, object]:
        return {"models": [{"id": "eval-simulated", "vision": False}]}

    async def embed_texts(self, texts: list[str], model: str, *, generation_lock: asyncio.Lock) -> list[list[float]]:
        if self.embed_gateway is None:
            raise RuntimeError("No embedding gateway is configured for this run.")
        return await self.embed_gateway.embed_texts(texts, model, generation_lock=generation_lock)

    def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock,
    ) -> AsyncIterator[dict]:
        self.prompts.append(messages)

        async def events() -> AsyncIterator[dict]:
            yield {"type": "thinking", "text": SIMULATED_THINKING}
            yield {"type": "token", "text": SIMULATED_ANSWER}
            yield {
                "type": "done",
                "model": "eval-simulated",
                "context": {
                    **(context_metadata or {}),
                    "used": (context_metadata or {}).get("used", 0),
                    "limit": context_limit,
                    "estimated": (context_metadata or {}).get("estimated", True),
                },
            }

        return events()


def _run_root(repo_root: Path) -> Path:
    root = repo_root.resolve(strict=True)
    local = root / ".local"
    if local.is_symlink():
        raise ValueError("Refusing to create evaluation output beneath a symlinked .local directory.")
    local.mkdir(exist_ok=True)
    evals = local / "evals"
    if evals.is_symlink():
        raise ValueError("Refusing to create evaluation output beneath a symlinked .local/evals directory.")
    evals.mkdir(exist_ok=True)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:10]}"
    path = evals / run_id
    if not path.resolve().is_relative_to(root):
        raise ValueError("Evaluation output escaped the repository root.")
    path.mkdir(parents=True, exist_ok=False)
    return path


def _snapshot_runtime_policy(repo_root: Path, run_dir: Path, source_path: Path | None) -> dict[str, str]:
    """Copy the authoritative policy into the run so prompt inputs remain auditable."""
    source = source_path if source_path is not None else repo_root.parent / "AGENTS.md"
    if source.is_symlink() or not source.is_file():
        raise ValueError("Runtime policy source is missing or unsafe.")
    try:
        contents = source.read_bytes()
        text = contents.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Runtime policy source cannot be read ({type(exc).__name__}).") from exc
    if not text.strip():
        raise ValueError("Runtime policy source is empty.")
    snapshot_path = run_dir / "runtime-policy.md"
    snapshot_path.write_bytes(contents)
    return {"sha256": hashlib.sha256(contents).hexdigest(), "snapshot": snapshot_path.name}


def _prepared_record(
    path: Path,
    repo_root: Path,
    source_hash: str,
    source_path: str,
) -> tuple[Path, dict[str, Any]]:
    """Validate an earlier run directory before reusing its parsed topic index."""
    root = repo_root.resolve(strict=True)
    result_path = path / "result.v1.json" if path.is_dir() else path
    candidate = result_path.parent
    if result_path.is_symlink() or any(parent.is_symlink() for parent in (candidate, *candidate.parents)):
        raise ValueError("Prepared evaluation runs cannot be loaded through symlink paths.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root / ".local" / "evals"):
        raise ValueError("Prepared evaluation run must be below this repository's .local/evals directory.")
    try:
        record = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f"Cannot read prepared evaluation result ({type(exc).__name__}).") from exc
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("Prepared evaluation result has an unsupported schema.")
    if (
        record.get("source", {}).get("sha256") != source_hash
        or record.get("source", {}).get("path") != source_path
        or record.get("provenance", {}).get("parser") != "docling"
        or record.get("provenance", {}).get("parser_version") is None
    ):
        raise ValueError("Prepared run source or parser provenance does not match the requested manifest.")
    if record.get("mode") not in {"keyword", "hybrid"} or record.get("exit_status") not in {
        "completed_descriptive_baseline",
        "extraction_limited_unscorable",
    }:
        raise ValueError("Prepared run must be a completed Whisper keyword or hybrid result.")
    if record.get("run_id") != resolved.name or not record.get("topic_id") or not record.get("file_id"):
        raise ValueError("Prepared run identity is malformed.")
    recorded_pages = record.get("page_count")
    recorded_source_pages = record.get("source", {}).get("physical_pages")
    if (
        (recorded_pages is not None and (type(recorded_pages) is not int or recorded_pages < 1))
        or (recorded_source_pages is not None and recorded_pages != recorded_source_pages)
        or record.get("mode") != record.get("provenance", {}).get("index_mode")
        or type(record.get("provenance", {}).get("retrieval_top_k")) is not int
        or type(record.get("provenance", {}).get("context_limit")) is not int
    ):
        raise ValueError("Prepared run parser/index settings are incomplete or inconsistent.")
    return resolved, record


def _stage_prepared_workspace(source_run: Path, output_dir: Path, topic_id: str) -> Path:
    """Copy a single validated topic into a new run, without its histories or traces."""
    source_learning = source_run / "Learning"
    if source_learning.is_symlink() or not source_learning.is_dir():
        raise ValueError("Prepared workspace Learning directory is missing or unsafe.")
    topic_source = None
    for candidate in source_learning.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        metadata = candidate / "topic.json"
        if metadata.is_symlink():
            raise ValueError("Prepared topic metadata cannot be a symlink.")
        if metadata.is_file() and json.loads(metadata.read_text(encoding="utf-8")).get("id") == topic_id:
            topic_source = candidate
            break
    if topic_source is None:
        raise ValueError("Prepared topic metadata does not match the recorded topic ID.")
    prior_settings = source_run / "settings.json"
    if prior_settings.is_symlink() or not prior_settings.is_file():
        raise ValueError("Prepared settings file is missing or unsafe.")
    for path in topic_source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Prepared topic artifacts cannot contain symlinks.")
    learning_target = output_dir / "Learning"
    learning_target.mkdir()
    topic_target = learning_target / topic_source.name
    topic_target.mkdir()
    for source in topic_source.iterdir():
        if source.is_dir():
            raise ValueError("Prepared topic contains an unexpected nested directory.")
        name = source.name
        if name == "query_traces.sqlite" or name.startswith("query_traces.sqlite-"):
            continue
        if name == "conversations.json" or (name.startswith("conversation_") and name.endswith(".json")):
            continue
        if name == "retrieval.sqlite" or name.startswith("retrieval.sqlite-"):
            continue
        shutil.copy2(source, topic_target / name)
    source_index = topic_source / "retrieval.sqlite"
    target_index = topic_target / "retrieval.sqlite"
    if not source_index.is_file() or source_index.is_symlink():
        raise ValueError("Prepared retrieval index is missing or unsafe.")
    source_connection = sqlite3.connect(source_index.as_uri() + "?mode=ro", uri=True)
    target_connection = sqlite3.connect(target_index)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    shutil.copy2(prior_settings, output_dir / "settings.json")
    return output_dir


def _validate_hybrid_index(index_path: Path, file_id: str, expected_model: str) -> dict[str, Any]:
    """Require complete, format-matched vectors for every selected file chunk."""
    connection = sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """SELECT c.chunk_id, c.has_embedding, e.model, e.dimension, length(e.vector)
               FROM chunks AS c LEFT JOIN chunk_embeddings AS e ON e.chunk_id = c.chunk_id
               WHERE c.file_id = ? ORDER BY c.chunk_index""",
            (file_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"Prepared hybrid index metadata is invalid ({type(exc).__name__}).") from exc
    finally:
        connection.close()
    if not rows:
        raise ValueError("Prepared hybrid index has no chunks for the selected file.")
    dimensions: set[int] = set()
    for _chunk_id, has_embedding, model, dimension, vector_bytes in rows:
        if has_embedding != 1 or model != expected_model or type(dimension) is not int or dimension < 1:
            raise ValueError("Prepared hybrid index has missing or mismatched embedding metadata.")
        if vector_bytes != dimension * 4:
            raise ValueError("Prepared hybrid index contains a truncated or malformed vector.")
        dimensions.add(dimension)
    if len(dimensions) != 1:
        raise ValueError("Prepared hybrid index vectors do not share a consistent dimension.")
    return {"chunk_count": len(rows), "embedding_model": expected_model, "dimension": next(iter(dimensions))}


def _relevant_source_hashes(repo_root: Path) -> dict[str, str]:
    paths = [Path("evals/retrieval") / name for name in ("manifest.py", "scorer.py", "runner.py")]
    paths.extend(Path("services/api/lab").rglob("*.py"))
    return {
        relative.as_posix(): hashlib.sha256((repo_root / relative).read_bytes()).hexdigest()
        for relative in sorted(set(paths))
        if (repo_root / relative).is_file()
    }


def _git_provenance(repo_root: Path) -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(repo_root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _normalize_hit(hit: Mapping[str, Any]) -> dict[str, Any]:
    trace = hit.get("trace")
    fusion = trace.get("fusion") if isinstance(trace, Mapping) else None
    if (
        not isinstance(fusion, Mapping)
        or type(fusion.get("rank")) is not int
        or type(fusion.get("score")) not in (int, float)
        or not math.isfinite(fusion["score"])
        or fusion["rank"] < 1
    ):
        raise RuntimeError("Production retrieval returned a hit without fusion rank and score metadata.")
    pages = hit.get("pages")
    if not isinstance(pages, list) or not pages or type(pages[0]) is not int or pages[0] < 1:
        raise RuntimeError("Production retrieval returned a hit without source pages.")
    if not isinstance(hit.get("chunk_id"), str) or not isinstance(hit.get("file_id"), str):
        raise RuntimeError("Production retrieval returned a hit without valid identifiers.")
    return {
        "chunk_id": hit.get("chunk_id"),
        "file_id": hit.get("file_id"),
        "page": pages[0],
        "rank": fusion["rank"],
        "score": fusion["score"],
    }


def _expected_citation(hit: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct the production citation record for a retained search hit."""
    text = str(hit.get("text", ""))
    citation: dict[str, Any] = {
        "chunk_id": hit.get("chunk_id"),
        "file_id": hit.get("file_id"),
        "file_name": hit.get("file_name"),
        "headings": hit.get("headings") or [],
        "pages": hit.get("pages") or [],
        "bboxes": hit.get("bboxes") or [],
        "assets": hit.get("asset_ids") or [],
        "trace": hit.get("trace", {}),
        "text": text[:600] + ("…" if len(text) > 600 else ""),
    }
    if "chunk_index" in hit:
        citation["chunk_index"] = hit["chunk_index"]
    return citation


def _expected_evidence_text(hit: Mapping[str, Any]) -> str:
    """Reconstruct the exact non-image evidence message built by retrieval."""
    headings = " > ".join(hit.get("headings") or [])
    pages = ", ".join(str(page) for page in hit.get("pages") or [])
    location = ", ".join(part for part in [hit["file_name"], headings, f"page {pages}" if pages else ""] if part)
    return f"UNTRUSTED RETRIEVED EVIDENCE ({location}):\n{hit['text']}"


def _check_trace(
    trace: Mapping[str, Any],
    expected_hits: list[dict[str, Any]],
    file_id: str,
    case_id: str,
    user_index: int,
    assistant_index: int,
    requested_top_k: int,
    context_limit: int,
    topic_id: str,
    expected_retained_ids: list[str],
    embedding_model: str | None,
    expected_retrieval_mode: str,
    expected_query_chars: int,
    expected_context: Mapping[str, Any],
    private_values: list[str],
) -> list[str]:
    failures: list[str] = []
    allowed_fields = {
        "id",
        "topic_id",
        "conversation_id",
        "schema_version",
        "started_at",
        "finished_at",
        "status",
        "query_chars",
        "requested_model",
        "requested_think",
        "context_limit",
        "actual_model",
        "embedding_model",
        "retrieval_top_k",
        "selected_file_ids",
        "retrieved_chunks",
        "retained_chunks",
        "retrieval_mode",
        "retrieval_warning",
        "prompt_budget",
        "context_used",
        "final_context",
        "cleanup_error",
        "preflight_ms",
        "retrieval_ms",
        "generation_ms",
        "first_output_ms",
        "total_ms",
        "output_chars",
        "thinking_chars",
        "stage",
        "error",
        "user_saved",
        "assistant_saved",
        "user_message_index",
        "assistant_message_index",
    }
    if set(trace) != allowed_fields:
        failures.append("trace_schema_fields_mismatch")
    if type(trace.get("schema_version")) is not int or trace.get("schema_version") != 1:
        failures.append("trace_schema_version_mismatch")
    if trace.get("status") != "completed":
        failures.append("trace_status_not_completed")
    if trace.get("stage") != "complete" or trace.get("error") is not None or trace.get("cleanup_error") is not None:
        failures.append("trace_completion_state_mismatch")
    if not isinstance(trace.get("id"), str) or not trace["id"]:
        failures.append("trace_id_missing")
    for field in ("started_at", "finished_at"):
        value = trace.get(field)
        try:
            timestamp = datetime.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            timestamp = None
        if timestamp is None or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            failures.append(f"trace_{field}_invalid")
        elif field == "started_at":
            started = timestamp
        elif "started" in locals() and timestamp < started:
            failures.append("trace_time_order_invalid")
    if trace.get("selected_file_ids") != [file_id]:
        failures.append("trace_file_selection_mismatch")
    if any(
        type(trace.get(field)) is not int or trace.get(field) != expected_value
        for field, expected_value in (
            ("query_chars", expected_query_chars),
            ("retrieval_top_k", requested_top_k),
            ("context_limit", context_limit),
        )
    ):
        failures.append("trace_numeric_request_metadata_invalid")
    if trace.get("requested_model") != "eval-simulated" or trace.get("actual_model") != "eval-simulated":
        failures.append("trace_model_provenance_mismatch")
    if trace.get("requested_think") is not None:
        failures.append("trace_request_metadata_mismatch")
    if trace.get("topic_id") != topic_id:
        failures.append("trace_topic_mismatch")
    if trace.get("embedding_model") != embedding_model:
        failures.append("trace_embedding_model_mismatch")
    if trace.get("retrieval_mode") != expected_retrieval_mode:
        failures.append("trace_retrieval_mode_mismatch")
    final_context = {
        key: expected_context[key]
        for key in ("used", "limit", "estimated", "truncated_messages")
        if key in expected_context
    }
    if trace.get("final_context") != final_context or trace.get("context_used") != expected_context.get("used"):
        failures.append("trace_context_does_not_match_saved_history")
    if trace.get("output_chars") != len(SIMULATED_ANSWER) or trace.get("thinking_chars") != len(SIMULATED_THINKING):
        failures.append("trace_output_character_counts_mismatch")
    actual_value = trace.get("retrieved_chunks", [])
    actual = actual_value if isinstance(actual_value, list) else []
    if not isinstance(actual_value, list):
        failures.append("trace_retrieved_chunks_invalid")
    expected = [_normalize_hit(hit) for hit in expected_hits]
    if actual != expected:
        failures.append("trace_hits_do_not_match_same_search")
    chunk_fields = {"chunk_id", "file_id", "page", "rank", "score"}
    if not all(isinstance(hit, Mapping) and set(hit) == chunk_fields for hit in actual):
        failures.append("trace_chunk_schema_mismatch")
    if any(_invalid_trace_chunk(hit) for hit in actual if isinstance(hit, Mapping)):
        failures.append("trace_chunk_values_invalid")
    retained_value = trace.get("retained_chunks", [])
    retained_records = retained_value if isinstance(retained_value, list) else []
    if not isinstance(retained_value, list):
        failures.append("trace_retained_chunks_invalid")
    retained = [item.get("chunk_id") for item in retained_records if isinstance(item, Mapping)]
    if len(retained) != len(set(retained)):
        failures.append("duplicate_retained_ids")
    if not set(retained).issubset({hit["chunk_id"] for hit in expected}):
        failures.append("retained_ids_not_in_hits")
    expected_retained_records = [hit for hit in expected if hit["chunk_id"] in set(expected_retained_ids)]
    if retained_records != expected_retained_records or retained != expected_retained_ids:
        failures.append("retained_trace_projection_mismatch")
    if not all(isinstance(hit, Mapping) and set(hit) == chunk_fields for hit in retained_records):
        failures.append("retained_chunk_schema_mismatch")
    if any(_invalid_trace_chunk(hit) for hit in retained_records if isinstance(hit, Mapping)):
        failures.append("retained_chunk_values_invalid")
    if _nested_trace_schema_invalid(trace):
        failures.append("trace_nested_schema_mismatch")
    for field in ("user_saved", "assistant_saved"):
        if trace.get(field) is not True:
            failures.append(f"{field}_false")
    if (
        type(trace.get("user_message_index")) is not int
        or type(trace.get("assistant_message_index")) is not int
        or trace.get("user_message_index") != user_index
        or trace.get("assistant_message_index") != assistant_index
    ):
        failures.append("saved_message_indices_mismatch")
    if _contains_prohibited_content_key(trace):
        failures.append("trace_contains_duplicated_content")
    trace_strings = list(_string_values(trace))
    if any(private and private in leaf for private in private_values for leaf in trace_strings):
        failures.append("trace_contains_private_text_value")
    for field in ("preflight_ms", "retrieval_ms", "generation_ms", "first_output_ms", "total_ms"):
        value = trace.get(field)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            failures.append(f"negative_or_invalid_{field}")
        if field in {"preflight_ms", "retrieval_ms", "generation_ms", "first_output_ms", "total_ms"} and value is None:
            failures.append(f"missing_{field}")
    if trace.get("conversation_id") != case_id:
        failures.append("conversation_scope_mismatch")
    return failures


def _invalid_trace_chunk(hit: Mapping[str, Any]) -> bool:
    score = hit.get("score")
    return (
        not isinstance(hit.get("chunk_id"), str)
        or not isinstance(hit.get("file_id"), str)
        or type(hit.get("page")) is not int
        or hit["page"] < 1
        or type(hit.get("rank")) is not int
        or hit["rank"] < 1
        or type(score) not in (int, float)
        or not math.isfinite(score)
    )


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [string for item in value.values() for string in _string_values(item)]
    if isinstance(value, list):
        return [string for item in value for string in _string_values(item)]
    return []


def _nested_trace_schema_invalid(trace: Mapping[str, Any]) -> bool:
    context = trace.get("final_context")
    if context is not None and (
        not isinstance(context, Mapping) or set(context) - {"used", "limit", "estimated", "truncated_messages"}
    ):
        return True
    error_fields = {"stage", "code", "exception_type", "summary"}
    for field in ("error", "cleanup_error"):
        error = trace.get(field)
        if error is not None and (not isinstance(error, Mapping) or set(error) != error_fields):
            return True
    return False


def _contains_prohibited_content_key(value: Any) -> bool:
    prohibited = {"query", "question", "prompt", "content", "text", "thinking", "answer", "passage", "images"}
    if isinstance(value, Mapping):
        return any(
            key.casefold() in prohibited or _contains_prohibited_content_key(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_prohibited_content_key(item) for item in value)
    return False


async def _local_embedding_tag(base_url: str, model: str) -> tuple[str, str]:
    """Resolve an installed embedding tag without attempting a download."""
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Embedding evaluation is restricted to the local Ollama service.")
    async with httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=10) as client:
        response = await client.get("/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
    match = next(
        (item for item in models if str(item.get("name", item.get("model", ""))).startswith(model + ":")),
        None,
    )
    if match is None:
        match = next((item for item in models if item.get("name") == model or item.get("model") == model), None)
    if match is None:
        raise ValueError(f"Hybrid evaluation requires already-installed local model {model!r}.")
    return str(match.get("model") or match.get("name")), str(match.get("digest") or "digest_unreported")


async def _execute_evaluation(
    repo_root: Path,
    manifest: LoadedManifest,
    *,
    output_dir: Path,
    mode: str,
    top_k: int,
    context_limit: int,
    runtime_policy_path: Path,
    ollama_url: str = "http://localhost:11434",
    workspace_dir: Path | None = None,
    prepared_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run questions on a fresh upload or validated prepared index."""
    if mode not in {"keyword", "hybrid"}:
        raise ValueError("Mode must be keyword or hybrid.")
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")
    if type(context_limit) is not int or not 1024 <= context_limit <= 32768:
        raise ValueError("context_limit must be between 1024 and 32768.")

    from lab.config import load_config
    from lab.embedding_config import embedding_index_key
    from lab.index import TopicIndex
    from lab.models import OllamaGateway
    from lab.storage import Store
    from lab.web.app import create_app

    assets = repo_root / "data/external/modelweights/docling"
    required_assets = (
        assets / "docling-project--docling-layout-heron/model.safetensors",
        assets
        / "docling-project--docling-models/model_artifacts/tableformer/accurate/tableformer_accurate.safetensors",
    )
    if prepared_record is None and any(not asset.is_file() for asset in required_assets):
        raise RuntimeError(
            "Required local Docling layout or table-structure assets are missing; no download was attempted."
        )

    source_fingerprint = _relevant_source_hashes(repo_root)
    git_fingerprint = _git_provenance(repo_root)
    started_at = time.monotonic()
    run_dir = output_dir
    requested_embedding_model = "nomic-embed-text" if mode == "hybrid" else None
    if mode == "hybrid":
        embedding_model, embedding_digest = await _local_embedding_tag(ollama_url, requested_embedding_model or "")
    else:
        embedding_model, embedding_digest = "", None
    workspace_dir = workspace_dir or run_dir
    settings_path = workspace_dir / "settings.json"
    expected_settings = {
        "model": "eval-simulated",
        "context_limit": context_limit,
        "parser": "docling",
        "embedding_model": embedding_model,
        "retrieval_top_k": top_k,
    }
    if prepared_record is None:
        settings_path.write_text(json.dumps(expected_settings, indent=2), encoding="utf-8")
    else:
        try:
            stored_settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ValueError(f"Prepared workspace settings cannot be read ({type(exc).__name__}).") from exc
        if stored_settings != expected_settings:
            raise ValueError("Prepared workspace settings do not match the prior evaluation provenance.")
        previous_digest = prepared_record["provenance"].get("actual_embedding_digest")
        if mode == "hybrid" and previous_digest not in {None, "digest_unreported", embedding_digest}:
            raise ValueError("Installed embedding digest changed since the prepared index was created.")
    learning_root = workspace_dir / "Learning"
    config = load_config(
        learning_root=learning_root,
        settings_path=settings_path,
        runtime_policy_path=runtime_policy_path,
        ollama_base_url=ollama_url,
        docling_artifacts_path=assets,
        embedding_tokenizer_root=repo_root / "data/external/modelweights/tokenizers",
    )
    gateway = SimulatedGateway(OllamaGateway(ollama_url) if mode == "hybrid" else None)
    captured: dict[str, dict[str, Any]] = {}

    async def capture_retrieval(*args: Any, **kwargs: Any) -> dict[str, object]:
        from lab.retrieval import search

        result = await search(*args, **kwargs)
        query = str(args[2])
        captured[query] = result
        return result

    app = create_app(config=config, model_backend=gateway, retriever=capture_retrieval)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        if prepared_record is None:
            topic_name = f"{manifest.source_path.stem.replace('_', ' ')} retrieval evaluation"
            topic_response = await client.post("/api/topics", json={"name": topic_name})
            topic_response.raise_for_status()
            topic_id = topic_response.json()["id"]
            settings_response = await client.put("/api/settings", json=expected_settings)
            settings_response.raise_for_status()
            upload_response = await client.post(
                f"/api/topics/{topic_id}/files",
                data={"parser": "docling"},
                files={"file": (manifest.source_path.name, manifest.source_bytes, "application/pdf")},
            )
            upload_response.raise_for_status()
            file_record = upload_response.json()
        else:
            topic_id = prepared_record["topic_id"]
            file_id = prepared_record["file_id"]
            file_record = app.state.deps.store.file(topic_id, file_id)
        if file_record.get("status") != "ready" or file_record.get("index_status") != "ready":
            raise RuntimeError("Docling upload/index did not become ready; evaluation infrastructure failed.")
        if mode == "hybrid" and file_record.get("index_mode") != "hybrid":
            raise RuntimeError("Hybrid run degraded during indexing; result is not a hybrid pass.")
        if mode == "keyword" and file_record.get("index_mode") != "keyword":
            raise RuntimeError("Keyword baseline unexpectedly used a different index mode.")
        if file_record.get("page_count") != manifest.data["source"]["physical_pages"]:
            raise RuntimeError("Docling page count does not match the manifest physical-page count.")
        verified_pdf_sha = hashlib.sha256(manifest.source_bytes).hexdigest()
        if file_record.get("content_sha256") != verified_pdf_sha:
            raise RuntimeError("Parsed file source hash does not match the verified selected PDF.")
        original_sha = hashlib.sha256(
            app.state.deps.store.file_path(topic_id, file_record["original_name"]).read_bytes()
        ).hexdigest()
        if original_sha != verified_pdf_sha:
            raise RuntimeError("The isolated topic original does not match the verified selected PDF.")
        if prepared_record is not None and file_record.get("parser_version") != prepared_record["provenance"].get(
            "parser_version"
        ):
            raise ValueError("Prepared topic parser version differs from its recorded result provenance.")
        if prepared_record is not None and file_record.get("index_mode") != prepared_record["provenance"].get(
            "index_mode"
        ):
            raise ValueError("Prepared topic index mode differs from its recorded result provenance.")
        with TopicIndex(app.state.deps.store.file_path(topic_id, "retrieval.sqlite"), read_only=True) as index:
            indexed_chunks = index.get_chunks(file_ids=[file_record["id"]])
        hybrid_index_metadata = None
        if mode == "hybrid":
            hybrid_index_metadata = _validate_hybrid_index(
                app.state.deps.store.file_path(topic_id, "retrieval.sqlite"),
                file_record["id"],
                embedding_index_key(embedding_model),
            )

        case_results: list[dict[str, Any]] = []
        hard_failures: list[str] = []
        for case in manifest.data["cases"]:
            conversation_response = await client.post(
                f"/api/topics/{topic_id}/conversations", json={"title": f"eval {case['id']}"}
            )
            conversation_response.raise_for_status()
            conversation_id = conversation_response.json()["id"]
            chat_response = await client.post(
                f"/api/topics/{topic_id}/conversations/{conversation_id}/chat",
                json={
                    "message": case["question"],
                    "file_ids": [file_record["id"]],
                    "model": "eval-simulated",
                    "context_limit": context_limit,
                },
            )
            chat_response.raise_for_status()
            events = [json.loads(line) for line in chat_response.text.splitlines() if line]
            done = next((event for event in events if event.get("type") == "done"), None)
            if done is None:
                raise RuntimeError(f"Chat lifecycle invariant failed for {case['id']}: no done event.")
            saved = (await client.get(f"/api/topics/{topic_id}/conversations/{conversation_id}/messages")).json()
            messages = saved["messages"]
            if [message["role"] for message in messages] != ["user", "assistant"]:
                raise RuntimeError(f"Saved history invariant failed for {case['id']}.")
            if messages[1].get("content") != SIMULATED_ANSWER or messages[1].get("thinking") != SIMULATED_THINKING:
                raise RuntimeError(f"Saved simulated output invariant failed for {case['id']}.")
            traces_response = await client.get(
                f"/api/topics/{topic_id}/query-traces",
                params={"conversation_id": conversation_id, "limit": 5},
            )
            traces_response.raise_for_status()
            traces = traces_response.json()["traces"]
            if len(traces) != 1:
                raise RuntimeError(f"Trace scoping invariant failed for {case['id']}.")
            raw_capture = captured.get(case["question"])
            if raw_capture is None:
                raise RuntimeError(f"Same-call retrieval capture missing for {case['id']}.")
            hits = raw_capture.get("hits", [])
            if mode == "hybrid" and raw_capture.get("mode") != "hybrid":
                hard_failures.append(f"{case['id']}:hybrid_retrieval_degraded")
            citations = done.get("retrieval", {}).get("citations", [])
            citation_ids = [item.get("chunk_id") for item in citations]
            retained = [item.get("chunk_id") for item in traces[0].get("retained_chunks", [])]
            score = score_case(case, indexed_chunks, hits, retained, top_k=top_k)
            expected_retained_ids = [hit["chunk_id"] for hit in hits if hit.get("chunk_id") in set(citation_ids)]
            if done.get("context") != saved.get("context"):
                hard_failures.append(f"{case['id']}:done_context_does_not_match_saved_history")
            invariant_failures = _check_trace(
                traces[0],
                hits,
                file_record["id"],
                conversation_id,
                0,
                1,
                top_k,
                context_limit,
                topic_id,
                expected_retained_ids,
                embedding_model,
                str(raw_capture.get("mode", "none")),
                len(case["question"]),
                saved.get("context", {}),
                [case["question"], SIMULATED_ANSWER, SIMULATED_THINKING] + [chunk["text"] for chunk in indexed_chunks],
            )
            saved_citations = messages[1].get("retrieval", {}).get("citations", [])
            saved_citation_ids = [item.get("chunk_id") for item in saved_citations]
            if saved_citations != done.get("retrieval", {}).get("citations", []):
                invariant_failures.append("saved_citations_do_not_match_done_event")
            expected_citations = [
                _expected_citation(hit) for hit in reversed(hits) if hit.get("chunk_id") in set(retained)
            ]
            if (
                saved_citations != expected_citations
                or len(saved_citation_ids) != len(set(saved_citation_ids))
                or set(saved_citation_ids) != set(retained)
            ):
                invariant_failures.append("saved_citations_do_not_match_retained_evidence")
            prompt_messages = gateway.prompts[-1]
            prompt_evidence = [
                message.get("content")
                for message in prompt_messages
                if message.get("role") == "user"
                and str(message.get("content", "")).startswith("UNTRUSTED RETRIEVED EVIDENCE (")
            ]
            expected_evidence = [
                _expected_evidence_text(hit) for hit in reversed(hits) if hit.get("chunk_id") in set(retained)
            ]
            if prompt_evidence != expected_evidence or prompt_messages[-1].get("content") != case["question"]:
                invariant_failures.append("retained_evidence_missing_from_prompt")
            if any(event.get("type") == "error" for event in events):
                invariant_failures.append("chat_stream_error")
            hard_failures.extend(f"{case['id']}:{failure}" for failure in invariant_failures)
            case_results.append({"case_id": case["id"], **score, "invariant_failures": invariant_failures})

    if (
        hashlib.sha256(manifest.source_path.read_bytes()).hexdigest()
        != hashlib.sha256(manifest.source_bytes).hexdigest()
    ):
        raise RuntimeError("Selected source changed during evaluation; this result cannot claim source immutability.")
    provenance = {
        **git_fingerprint,
        "runtime_policy": {
            "sha256": hashlib.sha256(runtime_policy_path.read_bytes()).hexdigest(),
            "snapshot": runtime_policy_path.name,
        },
        "source_file_sha256": hashlib.sha256(manifest.source_bytes).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest.manifest_bytes).hexdigest(),
        "relevant_source_sha256": source_fingerprint,
        "python": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in (
                "docling",
                "docling-core",
                "transformers",
                "tokenizers",
                "torch",
                "fastapi",
                "pydantic",
                "httpx",
            )
            if _has_distribution(name)
        },
        "sqlite_version": __import__("sqlite3").sqlite_version,
        "parser": file_record.get("parser"),
        "parser_version": file_record.get("parser_version"),
        "parser_warning_count": len(file_record.get("warnings") or []),
        "extraction_diagnostics_status": (file_record.get("extraction_diagnostics") or {}).get("status"),
        "index_mode": file_record.get("index_mode"),
        "requested_embedding_model": requested_embedding_model,
        "resolved_embedding_model": embedding_model or None,
        "actual_embedding_digest": embedding_digest,
        "hybrid_index": hybrid_index_metadata,
        "retrieval_top_k": top_k,
        "context_limit": context_limit,
    }
    result = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "started_at": datetime.fromtimestamp(time.time() - (time.monotonic() - started_at), UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "simulated_generation": True,
        "answer_quality_evaluated": False,
        "quality_gate_applied": False,
        "source": {
            "path": manifest.data["source"]["path"],
            "sha256": provenance["source_file_sha256"],
            "physical_pages": manifest.data["source"]["physical_pages"],
        },
        "topic_id": topic_id,
        "file_id": file_record["id"],
        "page_count": file_record.get("page_count"),
        "parser_coverage": {
            case["id"]: score_case(case, indexed_chunks, [], [], top_k=top_k)["extraction"]
            for case in manifest.data["cases"]
        },
        "cases": case_results,
        "hard_failures": hard_failures,
        "readiness": (
            "extraction_limited"
            if any(item["status"] == "extraction_limited" for item in case_results)
            else "infrastructure_validated"
        ),
        "provenance": provenance,
    }
    if hard_failures:
        result["exit_status"] = "failed_invariants"
    elif result["readiness"] == "extraction_limited":
        result["exit_status"] = "extraction_limited_unscorable"
    else:
        result["exit_status"] = "completed_descriptive_baseline"
    _write_result(run_dir, result)
    result["output_path"] = str(run_dir / "result.v1.json")
    return result


async def run_evaluation(
    repo_root: Path,
    manifest: LoadedManifest,
    *,
    mode: str | None = None,
    top_k: int | None = None,
    context_limit: int | None = None,
    ollama_url: str = "http://localhost:11434",
    prepared_run: Path | None = None,
    runtime_policy_path: Path | None = None,
) -> dict[str, Any]:
    """Create a durable run record, then execute a fresh or prepared-index replay."""
    output_dir = _run_root(repo_root)
    started = datetime.now(UTC).isoformat()
    state_path = output_dir / "run_state.json"
    state = {"schema_version": 1, "run_id": output_dir.name, "status": "started", "started_at": started}
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    snapshot: dict[str, Any] = {
        "source": {
            "path": manifest.data["source"]["path"],
            "sha256": hashlib.sha256(manifest.source_bytes).hexdigest(),
            "physical_pages": manifest.data["source"]["physical_pages"],
        },
        "manifest_sha256": hashlib.sha256(manifest.manifest_bytes).hexdigest(),
    }
    requested_settings: dict[str, Any] = {"mode": mode, "top_k": top_k, "context_limit": context_limit}
    state.update({"source": snapshot["source"], "manifest_sha256": snapshot["manifest_sha256"]})
    state["requested_settings"] = requested_settings
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    try:
        policy_provenance = _snapshot_runtime_policy(repo_root, output_dir, runtime_policy_path)
        snapshot["runtime_policy"] = policy_provenance
        snapshot["relevant_source_sha256"] = _relevant_source_hashes(repo_root)
        snapshot["git"] = _git_provenance(repo_root)
        state["provenance"] = snapshot
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        prior_workspace = None
        prior_record = None
        if prepared_run is not None:
            prior_workspace, prior_record = _prepared_record(
                prepared_run,
                repo_root,
                hashlib.sha256(manifest.source_bytes).hexdigest(),
                manifest.data["source"]["path"],
            )
            prior_workspace = _stage_prepared_workspace(
                prior_workspace,
                output_dir,
                prior_record["topic_id"],
            )
        chosen_mode = mode or (prior_record["mode"] if prior_record else "keyword")
        chosen_top_k = (
            top_k if top_k is not None else (prior_record["provenance"]["retrieval_top_k"] if prior_record else 6)
        )
        chosen_context = (
            context_limit
            if context_limit is not None
            else (prior_record["provenance"]["context_limit"] if prior_record else 16384)
        )
        requested_settings = {
            "mode": chosen_mode,
            "top_k": chosen_top_k,
            "context_limit": chosen_context,
            "prepared_from_run": prior_record["run_id"] if prior_record else None,
        }
        state["requested_settings"] = requested_settings
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        result = await _execute_evaluation(
            repo_root,
            manifest,
            output_dir=output_dir,
            mode=chosen_mode,
            top_k=chosen_top_k,
            context_limit=chosen_context,
            ollama_url=ollama_url,
            workspace_dir=prior_workspace,
            prepared_record=prior_record,
            runtime_policy_path=output_dir / policy_provenance["snapshot"],
        )
        final_policy_sha256 = hashlib.sha256((output_dir / policy_provenance["snapshot"]).read_bytes()).hexdigest()
        if final_policy_sha256 != policy_provenance["sha256"]:
            raise RuntimeError("Runtime policy snapshot changed during evaluation.")
        if prior_record is not None:
            result["prepared_from_run"] = prior_record["run_id"]
            result["provenance"]["prepared_parser_source_sha256"] = prior_record["provenance"].get(
                "relevant_source_sha256", {}
            )
            _write_result(output_dir, result)
        state.update({"status": result["exit_status"], "finished_at": datetime.now(UTC).isoformat()})
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        result["output_path"] = str(output_dir / "result.v1.json")
        return result
    except Exception as exc:
        # Persist only fixed exception metadata; avoid recording user questions or local paths.
        failure = {
            "schema_version": 1,
            "run_id": output_dir.name,
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(),
            "exit_status": "infrastructure_failed",
            "source": snapshot["source"],
            "requested_settings": requested_settings,
            "provenance": snapshot,
            "failure": {"exception_type": type(exc).__name__, "stage": "run"},
        }
        _write_result(output_dir, failure)
        state.update({"status": "infrastructure_failed", "finished_at": failure["finished_at"]})
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        raise


def _has_distribution(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def _write_result(run_dir: Path, result: Mapping[str, Any]) -> None:
    destination = run_dir / "result.v1.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("evals/retrieval/whisper.v1.json"))
    parser.add_argument("--mode", choices=("keyword", "hybrid"))
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--context-limit", type=int)
    parser.add_argument("--prepared-run", type=Path, help="Replay using a validated earlier run's parsed index.")
    parser.add_argument("--runtime-policy", type=Path, help="Use this policy file instead of the parent AGENTS.md.")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    api_root = str(repo_root / "services/api")
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    try:
        manifest = load_manifest(args.manifest, repo_root)
        result = asyncio.run(
            run_evaluation(
                repo_root,
                manifest,
                mode=args.mode,
                top_k=args.top_k,
                context_limit=args.context_limit,
                ollama_url=args.ollama_url,
                prepared_run=args.prepared_run,
                runtime_policy_path=args.runtime_policy,
            )
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports hard infrastructure failures clearly
        print(f"Retrieval evaluation infrastructure failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "exit_status": result["exit_status"],
                "output_path": result["output_path"],
                "case_count": len(result["cases"]),
            }
        )
    )
    return 1 if result["hard_failures"] or result["readiness"] == "extraction_limited" else 0


if __name__ == "__main__":
    raise SystemExit(main())
