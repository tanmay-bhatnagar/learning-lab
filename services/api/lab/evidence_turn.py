"""Finite answer-or-search model workflow for one protected chat turn."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from lab.contracts import ModelGateway
from lab.errors import Conflict, InvalidInput
from lab.evidence_prompt import EvidencePromptPlan
from lab.evidence_request import (
    MAX_SOURCE_REFERENCES,
    AnswerAction,
    evidence_action_schema,
    merge_scoped_sources,
    parse_evidence_action,
)
from lab.evidence_result import (
    INVALID_ACTION_WARNING as _INVALID_ACTION_WARNING,
    INVALID_OUTPUT as _INVALID_OUTPUT,
    LOOKUP_ERROR as _LOOKUP_ERROR,
    PROVIDER_ERROR as _PROVIDER_ERROR,
    checked_images as _checked_images,
    checked_scope as _checked_scope,
    close_stream as _close_stream,
    consume_decision as _consume_decision,
    initial_outcomes as _initial_outcomes,
    merge_images as _merge_images,
    retained_chunks as _retained_chunks,
    union_chunks as _union_chunks,
    validate_lookup_result as _validate_lookup_result,
)

Stage = Literal["deciding", "searching", "answering"]
EventKind = Literal["stage", "plan", "token", "thinking", "done", "error"]


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
    state["initial_chunk_ids"] = [str(source["chunk_id"]) for source in initial_retained]
    state["final_chunk_ids"] = list(state["initial_chunk_ids"])
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
    completed = False
    response_model: str | None = None
    response_context: dict[str, object] | None = None
    error_code: str | None = None
    saw_answer_text = False
    try:
        yield EvidenceTurnEvent(kind="plan", stage="answering", plan=plan, metadata=dict(state))
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
