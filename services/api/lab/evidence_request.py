"""Pure validation and source-scope helpers for one bounded evidence request."""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Literal, TypeAlias

from lab.errors import InvalidInput

MAX_ANSWER_BYTES = 64 * 1024
MAX_ACTION_BYTES = 80 * 1024
MAX_SEARCH_QUERY_CHARS = 500
MAX_SOURCE_REFERENCES = 64
_LABEL = re.compile(r"^E[1-9][0-9]*$")
_INLINE_MARKER = re.compile(r"\[E([^\]\r\n]*)\]")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class SourceReference:
    """Immutable label-to-index identity mapping for one retained chunk."""

    label: str
    source_id: str
    file_id: str
    file_name: str
    content_sha256: str
    pages: tuple[int, ...]


@dataclass(frozen=True)
class SourceImageReference:
    """Identity and byte hash for one image actually attached to retained evidence."""

    source_id: str
    file_id: str
    asset_name: str
    content_sha256: str


@dataclass(frozen=True)
class AnswerAction:
    """A complete buffered Markdown answer with validated initial-source references."""

    markdown: str
    references: tuple[SourceReference, ...]
    action: Literal["answer"] = "answer"


@dataclass(frozen=True)
class SearchSelectedAction:
    """A single bounded query over the server-captured selected-file scope."""

    query: str
    action: Literal["search_selected"] = "search_selected"


EvidenceAction: TypeAlias = AnswerAction | SearchSelectedAction


def build_source_manifest(chunks: Sequence[Mapping[str, object]]) -> tuple[SourceReference, ...]:
    """Label validated retained indexed chunks without granting new source authority."""
    if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
        raise InvalidInput("Initial evidence must be a sequence of indexed sources.")
    if len(chunks) > MAX_SOURCE_REFERENCES:
        raise InvalidInput("Initial evidence contains too many source references.")
    references = []
    seen = set()
    for index, chunk in enumerate(chunks, start=1):
        checked = _validate_indexed_chunk(chunk)
        if checked["chunk_id"] in seen:
            raise InvalidInput("Initial evidence contains duplicate indexed chunk IDs.")
        seen.add(checked["chunk_id"])
        references.append(
            SourceReference(
                label=f"E{index}",
                source_id=checked["chunk_id"],
                file_id=checked["file_id"],
                file_name=checked["file_name"],
                content_sha256=checked["content_hash"],
                pages=tuple(checked["pages"]),
            )
        )
    return tuple(references)


def evidence_action_schema(source_labels: Sequence[str]) -> dict[str, Any]:
    """Return a conservative one-object schema; parse-time checks enforce branch exclusivity."""
    labels = _validate_source_labels(source_labels)
    label_items: dict[str, Any] = {"type": "string", "enum": labels} if labels else {"type": "string"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "answer", "source_labels", "query"],
        "properties": {
            "action": {"type": "string", "enum": ["answer", "search_selected"]},
            "answer": {"type": "string", "maxLength": MAX_ANSWER_BYTES},
            "source_labels": {
                "type": "array",
                "items": label_items,
                "uniqueItems": True,
                "maxItems": len(labels),
            },
            "query": {"type": "string", "maxLength": MAX_SEARCH_QUERY_CHARS},
        },
    }


def parse_evidence_action(
    response: str | object,
    manifest: Sequence[SourceReference],
    *,
    can_search: bool,
) -> EvidenceAction:
    """Validate complete provider output, branch exclusivity, and all source references."""
    if type(can_search) is not bool:
        raise InvalidInput("Search availability must be explicit.")
    checked_manifest = _validate_manifest(manifest)
    if isinstance(response, str):
        try:
            encoded_response = response.encode("utf-8")
        except UnicodeEncodeError:
            raise InvalidInput("The evidence response is not valid Unicode text.") from None
        if len(encoded_response) > MAX_ACTION_BYTES:
            raise InvalidInput("The evidence response exceeded its structured-output limit.")
        try:
            value = json.loads(response, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError):
            raise InvalidInput("The evidence response was not one complete valid JSON object.") from None
    else:
        value = response
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise InvalidInput("The evidence response must be JSON-compatible.") from None
        if len(encoded) > MAX_ACTION_BYTES:
            raise InvalidInput("The evidence response exceeded its structured-output limit.")

    if not isinstance(value, dict) or set(value) != {"action", "answer", "source_labels", "query"}:
        raise InvalidInput("The evidence response must contain exactly the requested action fields.")
    action, answer, raw_labels, query = (
        value["action"],
        value["answer"],
        value["source_labels"],
        value["query"],
    )
    if not all(isinstance(item, str) for item in (action, answer, query)) or not isinstance(raw_labels, list):
        raise InvalidInput("The evidence response fields have invalid types.")
    if _CONTROL.search(answer) or any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise InvalidInput("The evidence response contains unsupported control characters.")
    try:
        answer_bytes = len(answer.encode("utf-8"))
        query.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidInput("The evidence response contains invalid Unicode text.") from None
    if answer_bytes > MAX_ANSWER_BYTES or len(query) > MAX_SEARCH_QUERY_CHARS:
        raise InvalidInput("The evidence response exceeded its answer or query limit.")
    labels = _validate_source_labels(raw_labels)
    available = {item.label: item for item in checked_manifest}
    if any(label not in available for label in labels):
        raise InvalidInput("The evidence response refers to a source outside the retained initial evidence.")

    if action == "answer":
        if not answer.strip() or query != "":
            raise InvalidInput("An answer action requires complete answer text and an empty search query.")
        markers = _INLINE_MARKER.findall(answer)
        if any(not _LABEL.fullmatch(f"E{marker}") for marker in markers):
            raise InvalidInput("Inline evidence markers must use a valid retained-source label.")
        inline_labels = {f"E{marker}" for marker in markers}
        if not inline_labels.issubset(set(labels)):
            raise InvalidInput("Inline evidence labels must be declared retained-source references.")
        return AnswerAction(markdown=answer, references=tuple(available[label] for label in labels))

    if action == "search_selected":
        if not can_search:
            raise InvalidInput("A selected-document search is unavailable for this request.")
        if answer != "" or labels or not query.strip():
            raise InvalidInput("A search action requires one non-empty query and no answer or source references.")
        return SearchSelectedAction(query=query)

    raise InvalidInput("The evidence response requested an unsupported action.")


def merge_scoped_sources(
    initial: Sequence[Mapping[str, object]],
    additional: Sequence[Mapping[str, object]],
    *,
    selected_file_ids: Set[str] | None,
    max_sources: int,
) -> tuple[dict[str, object], ...]:
    """Merge indexed chunks in initial-first order, only within an explicit non-empty file scope."""
    if (
        selected_file_ids is None
        or isinstance(selected_file_ids, (str, bytes))
        or not isinstance(selected_file_ids, Set)
        or not selected_file_ids
        or any(not isinstance(file_id, str) or not file_id.strip() for file_id in selected_file_ids)
    ):
        raise InvalidInput("Selected indexed-file scope must be explicit and non-empty.")
    if type(max_sources) is not int or not 1 <= max_sources <= MAX_SOURCE_REFERENCES:
        raise InvalidInput("The merged evidence limit must be a positive integer.")
    if (
        isinstance(initial, (str, bytes))
        or not isinstance(initial, Sequence)
        or isinstance(additional, (str, bytes))
        or not isinstance(additional, Sequence)
    ):
        raise InvalidInput("Initial and additional evidence must be indexed-chunk sequences.")
    merged: list[dict[str, object]] = []
    by_id: dict[str, dict[str, object]] = {}
    for chunk in (*initial, *additional):
        checked = _validate_indexed_chunk(chunk)
        if checked["file_id"] not in selected_file_ids:
            raise InvalidInput("Retrieved evidence is outside the selected indexed-file scope.")
        prior = by_id.get(checked["chunk_id"])
        if prior is not None:
            if prior["content_hash"] != checked["content_hash"] or prior["file_id"] != checked["file_id"]:
                raise InvalidInput("An indexed chunk ID resolved to conflicting source content.")
            continue
        by_id[checked["chunk_id"]] = checked
        merged.append(checked)
        if len(merged) > max_sources:
            raise InvalidInput("Merged evidence exceeds the configured source limit.")
    return tuple(merged)


def _validate_indexed_chunk(chunk: object) -> dict[str, object]:
    if not isinstance(chunk, Mapping):
        raise InvalidInput("Each source must be an indexed chunk record.")
    chunk_id, file_id, file_name = chunk.get("chunk_id"), chunk.get("file_id"), chunk.get("file_name")
    content, digest, pages = chunk.get("text"), chunk.get("content_hash"), chunk.get("pages")
    if (
        not isinstance(chunk_id, str)
        or not chunk_id.strip()
        or not isinstance(file_id, str)
        or not file_id.strip()
        or not isinstance(file_name, str)
        or not file_name.strip()
        or not isinstance(content, str)
        or not content.strip()
        or not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
        or not isinstance(pages, list)
        or any(type(page) is not int or page < 1 for page in pages)
    ):
        raise InvalidInput("An indexed chunk has invalid identity, content, hash, or page metadata.")
    try:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        raise InvalidInput("An indexed chunk contains invalid Unicode text.") from None
    if content_hash != digest:
        raise InvalidInput("An indexed chunk has invalid identity, content, hash, or page metadata.")
    checked = deepcopy(dict(chunk))
    checked["chunk_id"] = chunk_id
    checked["file_id"] = file_id
    checked["file_name"] = file_name
    checked["content_hash"] = digest
    checked["text"] = content
    checked["pages"] = list(pages)
    return checked


def _validate_source_labels(labels: Sequence[str]) -> tuple[str, ...]:
    if isinstance(labels, (str, bytes)) or not isinstance(labels, Sequence) or len(labels) > MAX_SOURCE_REFERENCES:
        raise InvalidInput("Evidence source labels must be a bounded list.")
    if any(not isinstance(label, str) or not _LABEL.fullmatch(label) for label in labels):
        raise InvalidInput("Evidence source labels are invalid.")
    if len(set(labels)) != len(labels):
        raise InvalidInput("Evidence source labels must be unique.")
    return tuple(labels)


def _validate_manifest(manifest: Sequence[SourceReference]) -> tuple[SourceReference, ...]:
    if isinstance(manifest, (str, bytes)) or not isinstance(manifest, Sequence):
        raise InvalidInput("The retained initial source manifest is invalid.")
    if len(manifest) > MAX_SOURCE_REFERENCES:
        raise InvalidInput("The retained initial source manifest is too large.")
    labels = []
    source_ids = set()
    for item in manifest:
        if not isinstance(item, SourceReference):
            raise InvalidInput("The retained initial source manifest contains an invalid reference.")
        if (
            not isinstance(item.label, str)
            or not _LABEL.fullmatch(item.label)
            or not isinstance(item.source_id, str)
            or not item.source_id.strip()
            or not isinstance(item.file_id, str)
            or not item.file_id.strip()
            or not isinstance(item.file_name, str)
            or not item.file_name.strip()
            or not isinstance(item.content_sha256, str)
            or not _SHA256.fullmatch(item.content_sha256)
            or not isinstance(item.pages, tuple)
            or any(type(page) is not int or page < 1 for page in item.pages)
        ):
            raise InvalidInput("The retained initial source manifest contains an invalid reference.")
        labels.append(item.label)
        if item.source_id in source_ids:
            raise InvalidInput("The retained initial source manifest contains duplicate source IDs.")
        source_ids.add(item.source_id)
    if len(labels) != len(set(labels)):
        raise InvalidInput("The retained initial source manifest contains duplicate labels.")
    return tuple(manifest)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value
