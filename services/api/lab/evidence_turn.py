"""Finite answer-or-search model workflow for one protected chat turn."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

from lab.contracts import ModelGateway
from lab.errors import Conflict, InvalidInput
from lab.evidence_prompt import EvidencePromptPlan
from lab.evidence_request import (
    MAX_ACTION_BYTES,
    MAX_SOURCE_REFERENCES,
    AnswerAction,
    SourceImageReference,
    SourceReference,
    evidence_action_schema,
    merge_scoped_sources,
    parse_evidence_action,
)

Stage = Literal["deciding", "searching", "answering"]
EventKind = Literal["stage", "plan", "token", "thinking", "done", "error"]
LookupMode = Literal["hybrid", "keyword", "fallback", "none"]


@dataclass(frozen=True)
class EvidenceTurnEvent:
    """A safe internal workflow update; planner JSON and search queries are never included."""

    kind: EventKind
    stage: Stage | None = None
    text: str | None = None
    error_code: str | None = None
    plan: EvidencePromptPlan | None = None
    metadata: dict[str, object] | None = None
    model: str | None = None
    context: dict[str, object] | None = None


SearchResult: TypeAlias = dict[str, object]
Lookup: TypeAlias = Callable[..., Awaitable[SearchResult]]
FinalPromptBuilder: TypeAlias = Callable[
    [Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]], EvidencePromptPlan
]
SnapshotGuard: TypeAlias = Callable[..., None]

_FALLBACK_WARNING = "Selected-document search used bounded opening passages because no query match was found."
_NO_HITS_WARNING = "No indexed passages were returned from the selected documents."
_KEYWORD_WARNING = "Semantic search was unavailable; keyword results were used."
_INVALID_ACTION_WARNING = "The structured planning response was unusable; no additional search was performed."
_PROVIDER_ERROR = "Evidence generation could not complete. Try again."
_LOOKUP_ERROR = "Selected-document search could not complete. Try again."
_INVALID_OUTPUT = "The selected model returned an incomplete evidence response. Try again."


def _initial_outcomes() -> dict[str, object]:
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


async def run_evidence_turn(
    *,
    gateway: ModelGateway,
    initial_plan: EvidencePromptPlan,
    initial_chunks: Sequence[Mapping[str, object]],
    selected_file_ids: tuple[str, ...],
    model: str,
    think: bool | str | None,
    context_limit: int,
    generation_lock: asyncio.Lock,
    lookup: Lookup,
    build_final: FinalPromptBuilder,
    revalidate: SnapshotGuard,
) -> AsyncIterator[EvidenceTurnEvent]:
    """Run one buffered structured decision, at most one scoped search, and one prose answer."""
    try:
        scope = _checked_scope(selected_file_ids)
    except (Conflict, InvalidInput):
        invalid_state = _initial_outcomes()
        invalid_state["outcome"] = "error"
        yield _error(
            "empty_indexed_scope",
            "Select an indexed document before asking for additional evidence.",
            invalid_state,
        )
        return
    initial_available = merge_scoped_sources(
        (), initial_chunks, selected_file_ids=set(scope), max_sources=MAX_SOURCE_REFERENCES
    )
    initial_retained = _retained_chunks(initial_plan, initial_available)
    initial_images = _checked_images(initial_plan.get("supplied_images", ()))
    state = {
        **_initial_outcomes(),
        "initial_available_chunk_ids": [str(source["chunk_id"]) for source in initial_available],
        "initial_chunk_ids": [str(source["chunk_id"]) for source in initial_retained],
        "final_chunk_ids": [str(source["chunk_id"]) for source in initial_retained],
    }

    yield _stage("deciding", state)
    try:
        revalidate(initial_retained, supplied_images=initial_images)
    except (Conflict, InvalidInput):
        state["outcome"] = "error"
        yield _error("snapshot_changed", _INVALID_OUTPUT, state)
        return
    state["generation_count"] = 1
    try:
        decision_stream = gateway.stream_chat(
            initial_plan["prompt"],
            model,
            think,
            context_limit,
            initial_plan["prompt_context"],
            generation_lock=generation_lock,
            response_schema=evidence_action_schema([reference.label for reference in initial_plan["source_manifest"]]),
        )
    except Exception:  # noqa: BLE001 - the selected gateway is an effect boundary.
        state["outcome"] = "error"
        yield _error("provider_failed", _PROVIDER_ERROR, state)
        return
    try:
        yield _stage("deciding", state)
        first = await _consume_decision(decision_stream)
    finally:
        await _close_stream(decision_stream)
    if first.error_code is not None:
        state["outcome"] = "error"
        yield _error(first.error_code, _PROVIDER_ERROR, state)
        return
    if not first.completed:
        state["outcome"] = "error"
        yield _error("incomplete_decision", _INVALID_OUTPUT, state)
        return

    try:
        action = parse_evidence_action(
            first.content,
            initial_plan["source_manifest"],
            can_search=bool(scope),
        )
    except InvalidInput:
        action = None

    if isinstance(action, AnswerAction):
        state["action"] = "answer"
        state["outcome"] = "direct_answer"
        state["declared_source_labels"] = [reference.label for reference in action.references]
        state["final_chunk_ids"] = [str(source["chunk_id"]) for source in initial_retained]
        yield _stage("answering", state)
        yield EvidenceTurnEvent(kind="token", text=action.markdown)
        yield _done_event(initial_plan, state, model=first.model, context=first.context)
        return

    if action is None:
        state["action"] = "invalid"
        state["warning"] = _INVALID_ACTION_WARNING
        state["outcome"] = "invalid_action_fallback"
        final_plan = build_final(initial_available, ())
        final_retained = _retained_chunks(final_plan, initial_available)
        final_images = _merge_images(initial_images, _checked_images(final_plan.get("supplied_images", ())))
        supplied = _union_chunks(initial_retained, final_retained)
        try:
            revalidate(supplied, supplied_images=final_images)
        except (Conflict, InvalidInput):
            state["outcome"] = "error"
            yield _error("snapshot_changed", _INVALID_OUTPUT, state)
            return
        final_stream = _stream_final(
            gateway,
            final_plan,
            model=model,
            think=think,
            context_limit=context_limit,
            generation_lock=generation_lock,
            state=state,
            final_chunk_ids=[str(source["chunk_id"]) for source in final_retained],
            retained_new_chunk_ids=[],
        )
        try:
            async for event in final_stream:
                if event.kind == "done":
                    yield _done_event(final_plan, state, model=event.model, context=event.context)
                else:
                    yield event
        finally:
            await _close_stream(final_stream)
        return

    state["action"] = "search_selected"
    state["outcome"] = "in_progress"
    try:
        revalidate(initial_retained, supplied_images=initial_images)
    except (Conflict, InvalidInput):
        state["outcome"] = "error"
        yield _error("snapshot_changed", _INVALID_OUTPUT, state)
        return
    state["lookup_count"] = 1
    try:
        lookup_task = asyncio.create_task(lookup(action.query, file_ids=scope))
    except Exception:  # noqa: BLE001 - retrieval invocation is an effect boundary.
        state["outcome"] = "error"
        yield _error("lookup_failed", _LOOKUP_ERROR, state)
        return
    try:
        yield _stage("searching", state)
        result = await lookup_task
    except asyncio.CancelledError:
        lookup_task.cancel()
        try:
            await lookup_task
        except asyncio.CancelledError:
            pass
        raise
    except GeneratorExit:
        lookup_task.cancel()
        try:
            await lookup_task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - cleanup must not mask generator closure.
            pass
        raise
    except Exception:  # noqa: BLE001 - retrieval is an effect boundary; never surface provider warning text.
        state["outcome"] = "error"
        yield _error("lookup_failed", _LOOKUP_ERROR, state)
        return
    finally:
        if not lookup_task.done():
            lookup_task.cancel()
            try:
                await lookup_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - cleanup must not mask the retrieval failure.
                pass

    try:
        returned, mode, search_warning = _validate_lookup_result(result, scope, initial_available)
    except InvalidInput:
        state["outcome"] = "error"
        yield _error("invalid_lookup_result", _LOOKUP_ERROR, state)
        return
    returned_ids = [str(source["chunk_id"]) for source in returned]
    state["returned_chunk_ids"] = returned_ids
    initial_available_ids = set(state["initial_available_chunk_ids"])
    state["new_chunk_ids"] = [chunk_id for chunk_id in returned_ids if chunk_id not in initial_available_ids]
    state["search_mode"] = mode
    state["search_warning"] = search_warning
    initial_ids_for_prompt = {str(source["chunk_id"]) for source in initial_available}
    novel_returned = tuple(source for source in returned if str(source["chunk_id"]) not in initial_ids_for_prompt)
    final_plan = build_final(initial_available, novel_returned)
    final_retained = _retained_chunks(
        final_plan,
        merge_scoped_sources(
            initial_available, returned, selected_file_ids=set(scope), max_sources=MAX_SOURCE_REFERENCES
        ),
    )
    final_images = _merge_images(initial_images, _checked_images(final_plan.get("supplied_images", ())))
    all_supplied = _union_chunks(initial_retained, final_retained)
    try:
        revalidate(all_supplied, supplied_images=final_images)
    except (Conflict, InvalidInput):
        state["outcome"] = "error"
        yield _error("snapshot_changed", _INVALID_OUTPUT, state)
        return
    initial_ids = set(state["initial_available_chunk_ids"])
    final_ids = [str(source["chunk_id"]) for source in final_retained]
    retained_new_ids = [
        chunk_id for chunk_id in final_ids if chunk_id in set(returned_ids) and chunk_id not in initial_ids
    ]
    state["outcome"] = "searched"
    final_stream = _stream_final(
        gateway,
        final_plan,
        model=model,
        think=think,
        context_limit=context_limit,
        generation_lock=generation_lock,
        state=state,
        final_chunk_ids=final_ids,
        retained_new_chunk_ids=retained_new_ids,
    )
    try:
        async for event in final_stream:
            if event.kind == "done":
                yield _done_event(final_plan, state, model=event.model, context=event.context)
            else:
                yield event
    finally:
        await _close_stream(final_stream)


@dataclass(frozen=True)
class _DecisionResult:
    content: str
    completed: bool
    model: str | None
    context: dict[str, object] | None
    error_code: str | None


async def _consume_decision(stream: AsyncIterator[dict]) -> _DecisionResult:
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
        close_error = await _close_stream(stream)
        if close_error is not None:
            error_code = "provider_close_failed"
            completed = False
    return _DecisionResult("".join(pieces), completed, model, context, error_code)


async def _stream_final(
    gateway: ModelGateway,
    plan: EvidencePromptPlan,
    *,
    model: str,
    think: bool | str | None,
    context_limit: int,
    generation_lock: asyncio.Lock,
    state: dict[str, object],
    final_chunk_ids: list[str],
    retained_new_chunk_ids: list[str],
) -> AsyncIterator[EvidenceTurnEvent]:
    state["generation_count"] = int(state["generation_count"]) + 1
    try:
        stream = gateway.stream_chat(
            plan["prompt"],
            model,
            think,
            context_limit,
            plan["prompt_context"],
            generation_lock=generation_lock,
            response_schema=None,
        )
    except Exception:  # noqa: BLE001 - never expose raw gateway boundary errors.
        state["outcome"] = "error"
        yield _error("provider_failed", _PROVIDER_ERROR, state)
        return
    state["final_chunk_ids"] = list(final_chunk_ids)
    state["retained_new_chunk_ids"] = list(retained_new_chunk_ids)
    yield EvidenceTurnEvent(kind="plan", stage="answering", plan=plan, metadata=dict(state))
    completed = False
    response_model: str | None = None
    response_context: dict[str, object] | None = None
    error_code: str | None = None
    saw_answer_text = False
    try:
        yield _stage("answering", state)
        async for event in stream:
            event_type = event.get("type") if isinstance(event, Mapping) else None
            if event_type in {"token", "thinking"}:
                text = event.get("text")
                if not isinstance(text, str):
                    error_code = "invalid_provider_event"
                    break
                if event_type == "token" and text.strip():
                    saw_answer_text = True
                yield EvidenceTurnEvent(kind=event_type, text=text)
                continue
            if event_type == "done":
                raw_model, raw_context = event.get("model"), event.get("context")
                if not isinstance(raw_model, str) or not isinstance(raw_context, dict):
                    error_code = "invalid_provider_completion"
                else:
                    completed = True
                    response_model = raw_model
                    response_context = dict(raw_context)
                break
            error_code = "provider_failed"
            break
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - the local model stream is an effect boundary.
        error_code = "provider_failed"
    finally:
        close_error = await _close_stream(stream)
        if close_error is not None:
            error_code = "provider_close_failed"
            completed = False
    if not completed or not saw_answer_text:
        state["outcome"] = "error"
        yield _error(error_code or "incomplete_answer", _PROVIDER_ERROR, state)
        return
    yield EvidenceTurnEvent(
        kind="done",
        plan=plan,
        metadata=dict(state),
        model=response_model,
        context=response_context,
    )


async def _close_stream(stream: AsyncIterator[dict]) -> str | None:
    close = getattr(stream, "aclose", None)
    if not callable(close):
        return None
    try:
        await close()
    except Exception:  # noqa: BLE001 - closing provider resources is part of the stream boundary.
        return "provider_close_failed"
    return None


def _checked_scope(file_ids: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not isinstance(file_ids, tuple)
        or not file_ids
        or any(not isinstance(file_id, str) or not file_id.strip() for file_id in file_ids)
        or len(set(file_ids)) != len(file_ids)
    ):
        raise InvalidInput("Select at least one indexed document before enabling an additional search.")
    return file_ids


def _retained_chunks(
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


def _checked_images(images: object) -> tuple[SourceImageReference, ...]:
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


def _merge_images(*groups: Sequence[SourceImageReference]) -> tuple[SourceImageReference, ...]:
    merged: dict[tuple[str, str, str], SourceImageReference] = {}
    for image in (item for group in groups for item in group):
        key = (image.source_id, image.file_id, image.asset_name)
        previous = merged.get(key)
        if previous is not None and previous != image:
            raise InvalidInput("A retained source image changed its byte identity during evidence generation.")
        merged[key] = image
    return tuple(merged.values())


def _union_chunks(*groups: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    ordered: dict[str, dict[str, object]] = {}
    for source in (item for group in groups for item in group):
        source_id = str(source["chunk_id"])
        previous = ordered.get(source_id)
        if previous is not None and previous != dict(source):
            raise InvalidInput("A retained source ID resolved to changed content during evidence generation.")
        ordered.setdefault(source_id, dict(source))
    return tuple(ordered.values())


def _validate_lookup_result(
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
        sanitized = _FALLBACK_WARNING
    elif mode == "none":
        sanitized = _NO_HITS_WARNING
    elif warning is not None and mode == "keyword":
        sanitized = _KEYWORD_WARNING
    return merged, mode, sanitized


def _stage(stage: Stage, state: dict[str, object]) -> EvidenceTurnEvent:
    return EvidenceTurnEvent(kind="stage", stage=stage, metadata=dict(state))


def _error(code: str, text: str, state: dict[str, object]) -> EvidenceTurnEvent:
    return EvidenceTurnEvent(kind="error", text=text, error_code=code, metadata=dict(state))


def _done_event(
    plan: EvidencePromptPlan,
    state: dict[str, object],
    *,
    model: str | None,
    context: dict[str, object] | None,
) -> EvidenceTurnEvent:
    return EvidenceTurnEvent(kind="done", plan=plan, metadata=dict(state), model=model, context=context)
