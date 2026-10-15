"""Immutable prompt-relevant snapshots for bounded evidence requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any

from lab.conversation_profile import get_conversation_profile
from lab.errors import Conflict, InvalidInput
from lab.evidence_request import MAX_SOURCE_REFERENCES, merge_scoped_sources
from lab.index import IndexInputError, TopicIndex
from lab.learner_context import load_learner_context
from lab.profile_store import ProfileStore
from lab.runtime_policy import load_runtime_policy
from lab.storage import Store, read_bytes, read_json

_FILE_FIELDS = (
    "id",
    "name",
    "original_name",
    "status",
    "index_status",
    "content_sha256",
    "parser",
    "parser_version",
    "markdown_name",
    "docling_name",
    "chunks_name",
    "parse_name",
    "page_count",
    "asset_count",
)
@dataclass(frozen=True)
class SourceProjection:
    """Identity and location metadata for text actually supplied to a provider."""

    chunk_id: str
    file_id: str
    file_name: str
    chunk_index: int
    text_sha256: str
    content_hash: str
    headings_json: str
    pages_json: str
    bboxes_json: str
    asset_ids_json: str


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Prompt-relevant hashes and source identities; never contains prompt text."""

    topic_id: str
    conversation_id: str
    include_cv: bool
    focus_sha256: str
    cv_id: str | None
    cv_name: str | None
    cv_text_sha256: str | None
    policy_sha256: str
    learning_goal_sha256: str
    learner_context_sha256: str
    selected_file_ids: frozenset[str]
    indexed_file_ids: frozenset[str]
    file_projections: tuple[str, ...]
    markdown_projections: tuple[tuple[str, str, str], ...]
    supplied_sources: tuple[SourceProjection, ...]
    digest: str


@dataclass(frozen=True)
class CapturedPromptContext:
    """Ephemeral raw prompt inputs kept separate from the immutable digest record."""

    snapshot: EvidenceSnapshot
    prompt_context: dict[str, Any]


def capture_prompt_context(
    *,
    store: Store,
    profile_store: ProfileStore,
    topic_id: str,
    conversation_id: str,
    selected_file_ids: Set[str],
    runtime_policy_path: Path,
) -> CapturedPromptContext:
    """Read current prompt inputs and return raw inputs separately from their snapshot."""
    if (
        isinstance(selected_file_ids, (str, bytes))
        or not isinstance(selected_file_ids, Set)
        or any(not isinstance(file_id, str) or not file_id.strip() for file_id in selected_file_ids)
    ):
        raise InvalidInput("Selected file identities must be an explicit set of IDs.")
    files, file_projections, indexed_ids, markdown, markdown_projections = _selected_files(
        store, topic_id, frozenset(selected_file_ids)
    )
    policy = load_runtime_policy(runtime_policy_path)
    topic = read_json(store.topic(topic_id) / "topic.json", {})
    goal = topic.get("learning_goal", "")
    if not isinstance(goal, str):
        raise Conflict("The topic learning goal changed to an unsupported value; reload before continuing.")
    preferences = get_conversation_profile(store, topic_id, conversation_id)
    cv_id, cv_name, cv_hash = _cv_identity(profile_store, preferences["include_cv"])
    learner = load_learner_context(
        store,
        profile_store,
        topic_id,
        conversation_id,
        pinned_preferences=preferences,
    )
    if _preference_projection(get_conversation_profile(store, topic_id, conversation_id)) != _preference_projection(
        preferences
    ):
        raise Conflict("Conversation learning context changed while evidence was being captured; retry the request.")
    if preferences["include_cv"] and hashlib.sha256(learner["cv_text"].encode("utf-8")).hexdigest() != cv_hash:
        raise Conflict("The selected CV changed while evidence was being captured; retry the request.")
    snapshot = _make_snapshot(
        topic_id=topic_id,
        conversation_id=conversation_id,
        preferences=preferences,
        cv_id=cv_id,
        cv_name=cv_name,
        cv_hash=cv_hash,
        policy=policy,
        goal=goal,
        learner_context=learner["learner_context"] or "",
        selected_file_ids=frozenset(selected_file_ids),
        indexed_file_ids=indexed_ids,
        file_projections=file_projections,
        markdown_projections=markdown_projections,
    )
    prompt_context = {
        "runtime_policy": policy,
        "learning_goal": goal,
        "learner_context": learner["learner_context"] or "",
        "cv_text": learner["cv_text"],
        "cv_name": learner["cv_name"],
        "attachments": markdown,
        "files": files,
    }
    return CapturedPromptContext(snapshot=snapshot, prompt_context=prompt_context)


def bind_retained_sources(
    snapshot: EvidenceSnapshot,
    sources: Sequence[Mapping[str, object]],
) -> EvidenceSnapshot:
    """Accumulate exact source projections across prompt stages without permitting ID drift."""
    if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence):
        raise InvalidInput("Retained evidence sources must be a sequence of indexed chunks.")
    if sources:
        checked = merge_scoped_sources(
            sources,
            (),
            selected_file_ids=snapshot.indexed_file_ids,
            max_sources=MAX_SOURCE_REFERENCES,
        )
    else:
        checked = ()
    existing = {source.chunk_id: source for source in snapshot.supplied_sources}
    for source in checked:
        projection = _source_projection(source)
        previous = existing.get(projection.chunk_id)
        if previous is not None and previous != projection:
            raise InvalidInput("A retained source ID resolved to changed content or location metadata.")
        existing[projection.chunk_id] = projection
    ordered = tuple(existing.values())
    return replace(snapshot, supplied_sources=ordered, digest=_snapshot_digest(snapshot, ordered))


def revalidate_evidence_snapshot(
    snapshot: EvidenceSnapshot,
    *,
    store: Store,
    profile_store: ProfileStore,
    runtime_policy_path: Path,
) -> None:
    """Reject changed prompt inputs or supplied sources before a later provider call."""
    preferences = get_conversation_profile(store, snapshot.topic_id, snapshot.conversation_id)
    if _preference_projection(preferences) != (snapshot.include_cv, snapshot.focus_sha256):
        raise Conflict("Conversation learning preferences changed during evidence generation; retry the request.")

    policy = load_runtime_policy(runtime_policy_path)
    topic = read_json(store.topic(snapshot.topic_id) / "topic.json", {})
    goal = topic.get("learning_goal", "")
    if not isinstance(goal, str) or _sha256(policy) != snapshot.policy_sha256 or _sha256(goal) != snapshot.learning_goal_sha256:
        raise Conflict("The runtime policy or topic learning goal changed during evidence generation; retry the request.")

    _cv_id, _cv_name, cv_hash = _cv_identity(profile_store, preferences["include_cv"])
    learner = load_learner_context(
        store,
        profile_store,
        snapshot.topic_id,
        snapshot.conversation_id,
        pinned_preferences=preferences,
    )
    after_preferences = get_conversation_profile(store, snapshot.topic_id, snapshot.conversation_id)
    if _preference_projection(after_preferences) != _preference_projection(preferences):
        raise Conflict("Conversation learning preferences changed during evidence validation; retry the request.")
    if (
        _sha256(learner["learner_context"] or "") != snapshot.learner_context_sha256
        or cv_hash != snapshot.cv_text_sha256
        or (preferences["include_cv"] and _sha256(learner["cv_text"] or "") != snapshot.cv_text_sha256)
    ):
        raise Conflict("Learner context or selected CV changed during evidence generation; retry the request.")

    _files, file_projections, indexed_ids, _markdown, markdown_projections = _selected_files(
        store, snapshot.topic_id, snapshot.selected_file_ids
    )
    if (
        file_projections != snapshot.file_projections
        or indexed_ids != snapshot.indexed_file_ids
        or markdown_projections != snapshot.markdown_projections
    ):
        raise Conflict("A selected source file or attachment changed during evidence generation; retry the request.")
    _revalidate_sources(store, snapshot)


def _selected_files(
    store: Store,
    topic_id: str,
    selected_file_ids: frozenset[str],
) -> tuple[list[dict[str, Any]], tuple[str, ...], frozenset[str], dict[str, str], tuple[tuple[str, str, str], ...]]:
    available = {record["id"]: record for record in store.files(topic_id) if isinstance(record.get("id"), str)}
    if not selected_file_ids.issubset(available):
        raise Conflict("A selected source file is no longer available in this topic.")
    files = [dict(available[file_id]) for file_id in sorted(selected_file_ids)]
    if any(record.get("status") != "ready" for record in files):
        raise Conflict("A selected source file is not ready for evidence retrieval.")
    indexed_ids = frozenset(record["id"] for record in files if record.get("index_status") == "ready")
    projections = tuple(_canonical_json({field: record[field] for field in _FILE_FIELDS if field in record}) for record in files)
    markdown: dict[str, str] = {}
    markdown_projections: list[tuple[str, str, str]] = []
    for record in files:
        if record.get("index_status") == "ready":
            continue
        markdown_name = record.get("markdown_name")
        if not isinstance(markdown_name, str) or not markdown_name:
            raise Conflict("A selected unindexed attachment has no saved Markdown text; retry after reprocessing it.")
        try:
            raw = read_bytes(store.file_path(topic_id, markdown_name))
            text = raw.decode("utf-8")
        except (UnicodeError, OSError):
            raise Conflict("A selected unindexed attachment changed or is unavailable; retry the request.") from None
        markdown[record["id"]] = text
        markdown_projections.append((record["id"], markdown_name, hashlib.sha256(raw).hexdigest()))
    return files, projections, indexed_ids, markdown, tuple(markdown_projections)


def _cv_identity(profile_store: ProfileStore, include_cv: bool) -> tuple[str | None, str | None, str | None]:
    if not include_cv:
        return None, None, None
    profile = profile_store.read_profile()
    cv_id = profile["active_cv_id"]
    record = next((item for item in profile["cvs"] if item["id"] == cv_id), None)
    if record is None or record["status"] != "ready" or record["revoked"]:
        raise Conflict("The selected CV is no longer eligible for this evidence request.")
    return cv_id, record["original_name"], record["extracted_sha256"]


def _source_projection(source: Mapping[str, object]) -> SourceProjection:
    text = source.get("text")
    if not isinstance(text, str):
        raise InvalidInput("A retained indexed source has no text to bind.")
    return SourceProjection(
        chunk_id=str(source["chunk_id"]),
        file_id=str(source["file_id"]),
        file_name=str(source["file_name"]),
        chunk_index=int(source["chunk_index"]),
        text_sha256=_sha256(text),
        content_hash=str(source["content_hash"]),
        headings_json=_canonical_json(source.get("headings", [])),
        pages_json=_canonical_json(source.get("pages", [])),
        bboxes_json=_canonical_json(source.get("bboxes", [])),
        asset_ids_json=_canonical_json(source.get("asset_ids", [])),
    )


def _revalidate_sources(store: Store, snapshot: EvidenceSnapshot) -> None:
    if not snapshot.supplied_sources:
        return
    chunk_ids = sorted(source.chunk_id for source in snapshot.supplied_sources)
    file_ids = sorted({source.file_id for source in snapshot.supplied_sources})
    try:
        with TopicIndex(store.topic(snapshot.topic_id) / "retrieval.sqlite", read_only=True) as index:
            rows = index.get_chunks(chunk_ids=chunk_ids, file_ids=file_ids)
    except (IndexInputError, OSError):
        raise Conflict("Retained indexed evidence is no longer available; retry the evidence request.") from None
    current = {str(row["chunk_id"]): _source_projection(row) for row in rows}
    expected = {source.chunk_id: source for source in snapshot.supplied_sources}
    if current != expected:
        raise Conflict("Retained indexed evidence changed during generation; retry the evidence request.")


def _make_snapshot(
    *,
    topic_id: str,
    conversation_id: str,
    preferences: dict[str, Any],
    cv_id: str | None,
    cv_name: str | None,
    cv_hash: str | None,
    policy: str,
    goal: str,
    learner_context: str,
    selected_file_ids: frozenset[str],
    indexed_file_ids: frozenset[str],
    file_projections: tuple[str, ...],
    markdown_projections: tuple[tuple[str, str, str], ...],
) -> EvidenceSnapshot:
    focus_sha256 = _sha256(_canonical_json(preferences["active_assessment"]))
    values = {
        "topic_id": topic_id,
        "conversation_id": conversation_id,
        "include_cv": preferences["include_cv"],
        "focus_sha256": focus_sha256,
        "cv_id": cv_id,
        "cv_name": cv_name,
        "cv_text_sha256": cv_hash,
        "policy_sha256": _sha256(policy),
        "learning_goal_sha256": _sha256(goal),
        "learner_context_sha256": _sha256(learner_context),
        "selected_file_ids": selected_file_ids,
        "indexed_file_ids": indexed_file_ids,
        "file_projections": file_projections,
        "markdown_projections": markdown_projections,
        "supplied_sources": (),
    }
    return EvidenceSnapshot(**values, digest=_snapshot_digest_values(values))


def _preference_projection(preferences: dict[str, Any]) -> tuple[bool, str]:
    return preferences["include_cv"], _sha256(_canonical_json(preferences["active_assessment"]))


def _snapshot_digest(snapshot: EvidenceSnapshot, sources: tuple[SourceProjection, ...]) -> str:
    values = {field: getattr(snapshot, field) for field in EvidenceSnapshot.__dataclass_fields__ if field != "digest"}
    values["supplied_sources"] = sources
    return _snapshot_digest_values(values)


def _snapshot_digest_values(values: dict[str, Any]) -> str:
    return _sha256(_canonical_json(_digest_payload(values)))


def _digest_payload(values: dict[str, Any]) -> dict[str, Any]:
    return {
        **values,
        "selected_file_ids": sorted(values["selected_file_ids"]),
        "indexed_file_ids": sorted(values["indexed_file_ids"]),
        "markdown_projections": [list(item) for item in values["markdown_projections"]],
        "supplied_sources": [
            {
                "chunk_id": source.chunk_id,
                "file_id": source.file_id,
                "file_name": source.file_name,
                "chunk_index": source.chunk_index,
                "text_sha256": source.text_sha256,
                "content_hash": source.content_hash,
                "headings_json": source.headings_json,
                "pages_json": source.pages_json,
                "bboxes_json": source.bboxes_json,
                "asset_ids_json": source.asset_ids_json,
            }
            for source in values["supplied_sources"]
        ],
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
