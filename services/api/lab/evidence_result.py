"""Pure evidence workflow helpers: scope, retained sources, lookup validation, decision buffering."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from lab.errors import InvalidInput
from lab.evidence_prompt import EvidencePromptPlan
from lab.evidence_request import (
    MAX_ACTION_BYTES,
    MAX_SOURCE_REFERENCES,
    SourceImageReference,
    SourceReference,
    merge_scoped_sources,
)

LookupMode = Literal["hybrid", "keyword", "fallback", "none"]

FALLBACK_WARNING = "Selected-document search used bounded opening passages because no query match was found."
NO_HITS_WARNING = "No indexed passages were returned from the selected documents."
KEYWORD_WARNING = "Semantic search was unavailable; keyword results were used."
INVALID_ACTION_WARNING = "The structured planning response was unusable; no additional search was performed."
PROVIDER_ERROR = "Evidence generation could not complete. Try again."
LOOKUP_ERROR = "Selected-document search could not complete. Try again."
INVALID_OUTPUT = "The selected model returned an incomplete evidence response. Try again."


def initial_outcomes() -> dict[str, object]:
    return {
        "schema_version": 1,
        "requested": True,
        "action": None,
        "outcome": "in_progress",
        "generation_count": 0,
        "lookup_count": 0,
        "initial_available_chunk_ids": [],
        "initial_chunk_ids": [],
        "returned_chunk_ids": [],
        "new_chunk_ids": [],
        "retained_new_chunk_ids": [],
        "final_chunk_ids": [],
        "declared_source_labels": [],
        "search_mode": None,
        "search_warning": None,
        "warning": None,
    }


@dataclass(frozen=True)
class _DecisionResult:
    content: str
    completed: bool
    model: str | None
    context: dict[str, object] | None
    error_code: str | None


async def consume_decision(stream: AsyncIterator[dict]) -> _DecisionResult:
    pieces: list[str] = []
    size = 0
    completed = False
    model: str | None = None
    context: dict[str, object] | None = None
    error_code = None
    try:
        async for event in stream:
            event_type = event.get("type") if isinstance(event, Mapping) else None
            if event_type == "thinking":
                continue
            if event_type == "token":
                text = event.get("text")
                if not isinstance(text, str):
                    error_code = "invalid_provider_event"
                    break
                try:
                    size += len(text.encode("utf-8"))
                except UnicodeEncodeError:
                    error_code = "invalid_provider_text"
                    break
                if size > MAX_ACTION_BYTES:
                    error_code = "action_too_large"
                    break
                pieces.append(text)
                continue
            if event_type == "done":
                raw_model, raw_context = event.get("model"), event.get("context")
                if not isinstance(raw_model, str) or not isinstance(raw_context, dict):
                    error_code = "invalid_provider_completion"
                else:
                    completed = True
                    model = raw_model
                    context = dict(raw_context)
                break
            error_code = "provider_failed"
            break
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - the local model stream is an effect boundary.
        error_code = "provider_failed"
    finally:
        close_error = await close_stream(stream)
        if close_error is not None:
            error_code = "provider_close_failed"
            completed = False
    return _DecisionResult("".join(pieces), completed, model, context, error_code)


async def close_stream(stream: AsyncIterator[dict]) -> str | None:
    close = getattr(stream, "aclose", None)
    if not callable(close):
        return None
    try:
        await close()
    except Exception:  # noqa: BLE001 - closing provider resources is part of the stream boundary.
        return "provider_close_failed"
    return None


def checked_scope(file_ids: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not isinstance(file_ids, tuple)
        or not file_ids
        or any(not isinstance(file_id, str) or not file_id.strip() for file_id in file_ids)
        or len(set(file_ids)) != len(file_ids)
    ):
        raise InvalidInput("Select at least one indexed document before enabling an additional search.")
    return file_ids


def retained_chunks(
    plan: EvidencePromptPlan,
    available: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    manifest = plan.get("source_manifest")
    if not isinstance(manifest, (tuple, list)):
        raise InvalidInput("Evidence prompt plan is missing its retained source manifest.")
    by_id = {str(source["chunk_id"]): source for source in available}
    retained: list[dict[str, object]] = []
    seen: set[str] = set()
    for reference in manifest:
        if not isinstance(reference, SourceReference) or reference.source_id in seen:
            raise InvalidInput("Evidence prompt plan has an invalid retained source manifest.")
        source = by_id.get(reference.source_id)
        if (
            source is None
            or source["file_id"] != reference.file_id
            or source["file_name"] != reference.file_name
            or source["content_hash"] != reference.content_sha256
            or tuple(source["pages"]) != reference.pages
        ):
            raise InvalidInput("Evidence prompt manifest does not match the full supplied source records.")
        retained.append(dict(source))
        seen.add(reference.source_id)
    return tuple(retained)


def checked_images(images: object) -> tuple[SourceImageReference, ...]:
    if not isinstance(images, (tuple, list)):
        raise InvalidInput("Evidence prompt plan has invalid retained image references.")
    checked: list[SourceImageReference] = []
    keys: set[tuple[str, str, str]] = set()
    for image in images:
        if not isinstance(image, SourceImageReference):
            raise InvalidInput("Evidence prompt plan has invalid retained image references.")
        key = (image.source_id, image.file_id, image.asset_name)
        if key in keys:
            raise InvalidInput("Evidence prompt plan has duplicate retained image references.")
        keys.add(key)
        checked.append(image)
    return tuple(checked)


def merge_images(*groups: Sequence[SourceImageReference]) -> tuple[SourceImageReference, ...]:
    merged: dict[tuple[str, str, str], SourceImageReference] = {}
    for image in (item for group in groups for item in group):
        key = (image.source_id, image.file_id, image.asset_name)
        previous = merged.get(key)
        if previous is not None and previous != image:
            raise InvalidInput("A retained source image changed its byte identity during evidence generation.")
        merged[key] = image
    return tuple(merged.values())


def union_chunks(*groups: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    ordered: dict[str, dict[str, object]] = {}
    for source in (item for group in groups for item in group):
        source_id = str(source["chunk_id"])
        previous = ordered.get(source_id)
        if previous is not None and previous != dict(source):
            raise InvalidInput("A retained source ID resolved to changed content during evidence generation.")
        ordered.setdefault(source_id, dict(source))
    return tuple(ordered.values())


def validate_lookup_result(
    result: object,
    file_ids: tuple[str, ...],
    initial: Sequence[Mapping[str, object]],
) -> tuple[tuple[dict[str, object], ...], LookupMode, str | None]:
    if not isinstance(result, Mapping):
        raise InvalidInput("Selected-document search returned an invalid result.")
    hits, mode, warning = result.get("hits"), result.get("mode"), result.get("warning")
    if (
        isinstance(hits, (str, bytes))
        or not isinstance(hits, Sequence)
        or mode not in {"hybrid", "keyword", "fallback", "none"}
        or (warning is not None and not isinstance(warning, str))
    ):
        raise InvalidInput("Selected-document search returned invalid evidence metadata.")
    merged = merge_scoped_sources((), hits, selected_file_ids=set(file_ids), max_sources=MAX_SOURCE_REFERENCES)
    merge_scoped_sources(initial, merged, selected_file_ids=set(file_ids), max_sources=MAX_SOURCE_REFERENCES)
    mode = cast(LookupMode, mode)
    sanitized = None
    if mode == "fallback":
        sanitized = FALLBACK_WARNING
    elif mode == "none":
        sanitized = NO_HITS_WARNING
    elif warning is not None and mode == "keyword":
        sanitized = KEYWORD_WARNING
    return merged, mode, sanitized
