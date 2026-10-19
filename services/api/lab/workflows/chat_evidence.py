"""Opt-in (extra_search) chat execution graph nodes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

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
    INVALID_ACTION_WARNING,
    INVALID_OUTPUT,
    LOOKUP_ERROR,
    PROVIDER_ERROR,
    checked_images,
    checked_scope,
    close_stream,
    consume_decision,
    initial_outcomes,
    merge_images,
    retained_chunks,
    union_chunks,
    validate_lookup_result,
)
from lab.query_traces import retrieval_fields
from lab.workflows.chat import workflow_graph_callables
from lab.workflows.chat_publication import (
    ChatOptInObserver,
    ChatOptInPublicationBundle,
    ChatPublicationOutcome,
    prepare_optin_publication,
)
from lab.workflows.events import EventSink, text_fragments

logger = logging.getLogger(__name__)

OPTIN_EXECUTION_RECURSION_LIMIT = 12

LookupFn = Callable[..., Awaitable[dict[str, object]]]
BuildFinalFn = Callable[
    [Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]],
    EvidencePromptPlan,
]
RevalidateFn = Callable[..., None]
SnapshotGuard = RevalidateFn


class ChatOptInState(TypedDict, total=False):
    route: str
    stage: str


@dataclass
class ChatOptInExecutionContext:
    model_backend: Any
    generation_lock: asyncio.Lock
    sink: EventSink
    bundle: ChatOptInPublicationBundle
    initial_plan: EvidencePromptPlan
    initial_chunks: tuple[dict[str, object], ...]
    evidence_scope: tuple[str, ...]
    model: str
    think: bool | str | None
    context_limit: int
    lookup: LookupFn
    build_final: BuildFinalFn
    revalidate: RevalidateFn
    observer: ChatOptInObserver
    evidence_state: dict[str, object] = field(default_factory=dict)
    initial_available: tuple[dict[str, object], ...] = ()
    initial_retained: tuple[dict[str, object], ...] = ()
    initial_images: tuple[Any, ...] = ()
    final_plan: EvidencePromptPlan | None = None
    publication_outcome: ChatPublicationOutcome | None = None
    provider_stream: Any = None
    last_emitted_stage: str | None = None
    latest_search_result: dict[str, object] | None = None
    total_retrieval_ms: float = 0.0
    file_ids: list[str] = field(default_factory=list)


async def _emit_evidence_status(ctx: ChatOptInExecutionContext, stage: str) -> None:
    ctx.observer.workflow_stage = stage
    if ctx.last_emitted_stage == stage:
        return
    ctx.last_emitted_stage = stage
    event: dict[str, object] = {"type": "evidence_status", "stage": stage}
    warning = ctx.evidence_state.get("warning") or ctx.evidence_state.get("search_warning")
    if isinstance(warning, str):
        event["warning"] = warning
    await ctx.sink.send(event)


def _record_initial_supply(ctx: ChatOptInExecutionContext) -> None:
    supplied_ids = {item for item in ctx.evidence_state.get("initial_chunk_ids", []) if isinstance(item, str)}
    if not supplied_ids:
        return
    initial_citations = [
        citation for citation in ctx.bundle.initial_plan["citations"] if citation.get("chunk_id") in supplied_ids
    ]
    ctx.bundle.retrieval_record["citations"] = initial_citations
    ctx.bundle.trace.record = retrieval_fields(
        ctx.bundle.trace.record,
        selected_file_ids=list(dict.fromkeys(ctx.file_ids)),
        search_result=ctx.bundle.search_result,
        retained_ids=supplied_ids,
        citations=initial_citations,
        retrieval_ms=ctx.total_retrieval_ms,
    )
    ctx.bundle.trace.record["evidence_search"] = dict(ctx.evidence_state)


async def evidence_init_node(_state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> ChatOptInState:
    ctx = runtime.context
    try:
        scope = checked_scope(ctx.evidence_scope)
    except (Conflict, InvalidInput):
        ctx.evidence_state = {**initial_outcomes(), "outcome": "error"}
        ctx.observer.set_workflow_error(
            "empty_indexed_scope", "Select an indexed document before asking for additional evidence."
        )
        return {"route": "error", "stage": "init"}
    ctx.evidence_scope = scope
    ctx.initial_available = merge_scoped_sources(
        (),
        ctx.initial_chunks,
        selected_file_ids=set(scope),
        max_sources=MAX_SOURCE_REFERENCES,
    )
    ctx.initial_retained = retained_chunks(ctx.initial_plan, ctx.initial_available)
    ctx.initial_images = checked_images(ctx.initial_plan.get("supplied_images", ()))
    ctx.evidence_state = {
        **initial_outcomes(),
        "initial_available_chunk_ids": [str(source["chunk_id"]) for source in ctx.initial_available],
    }
    ctx.bundle.trace.record["evidence_search"] = dict(ctx.evidence_state)
    await _emit_evidence_status(ctx, "deciding")
    try:
        ctx.revalidate(ctx.initial_retained, supplied_images=ctx.initial_images)
    except (Conflict, InvalidInput):
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("snapshot_changed", INVALID_OUTPUT)
        return {"route": "error", "stage": "init"}
    return {"route": "continue", "stage": "init"}


async def route_after_init(state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> str:
    del runtime
    return "error" if state.get("route") == "error" else "decision"


async def decision_node(_state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> ChatOptInState:
    ctx = runtime.context
    ctx.evidence_state["generation_count"] = 1
    manifest = ctx.initial_plan["source_manifest"]
    labels = [reference.label for reference in manifest]
    try:
        decision_stream = ctx.model_backend.stream_chat(
            ctx.initial_plan["prompt"],
            ctx.model,
            ctx.think,
            ctx.context_limit,
            ctx.initial_plan["prompt_context"],
            generation_lock=ctx.generation_lock,
            response_schema=evidence_action_schema(labels),
        )
    except Exception:  # noqa: BLE001 - gateway boundary
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("provider_failed", PROVIDER_ERROR)
        return {"route": "error", "stage": "deciding"}
    ctx.evidence_state["initial_chunk_ids"] = [str(source["chunk_id"]) for source in ctx.initial_retained]
    ctx.evidence_state["final_chunk_ids"] = list(ctx.evidence_state["initial_chunk_ids"])
    await _emit_evidence_status(ctx, "deciding")
    if ctx.evidence_state.get("generation_count") == 1:
        _record_initial_supply(ctx)
    try:
        first = await consume_decision(decision_stream)
    finally:
        await close_stream(decision_stream)
    if first.error_code is not None:
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error(first.error_code, PROVIDER_ERROR)
        return {"route": "error", "stage": "deciding"}
    if not first.completed:
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("incomplete_decision", INVALID_OUTPUT)
        return {"route": "error", "stage": "deciding"}
    try:
        action = parse_evidence_action(first.content, manifest, can_search=bool(ctx.evidence_scope))
    except InvalidInput:
        action = None
    ctx.observer.decision_model = first.model
    ctx.observer.decision_context = first.context
    if isinstance(action, AnswerAction):
        ctx.evidence_state["action"] = "answer"
        ctx.evidence_state["outcome"] = "direct_answer"
        ctx.evidence_state["declared_source_labels"] = [reference.label for reference in action.references]
        ctx.evidence_state["final_chunk_ids"] = [str(source["chunk_id"]) for source in ctx.initial_retained]
        ctx.observer.direct_answer_text = action.markdown
        ctx.final_plan = ctx.initial_plan
        return {"route": "direct", "stage": "deciding"}
    if action is None:
        ctx.evidence_state["action"] = "invalid"
        ctx.evidence_state["warning"] = INVALID_ACTION_WARNING
        ctx.evidence_state["outcome"] = "invalid_action_fallback"
        return {"route": "invalid", "stage": "deciding"}
    ctx.evidence_state["action"] = "search_selected"
    ctx.evidence_state["outcome"] = "in_progress"
    ctx.observer.search_query = action.query
    return {"route": "search", "stage": "deciding"}


async def route_after_decision(state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> str:
    del runtime
    route = state.get("route", "error")
    if route in {"direct", "invalid", "search", "error"}:
        return route
    return "error"


async def direct_answer_node(_state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> ChatOptInState:
    ctx = runtime.context
    await _emit_evidence_status(ctx, "answering")
    text = ctx.observer.direct_answer_text or ""
    if text:
        ctx.observer.record_token("token", text)
        for fragment in text_fragments(text):
            await ctx.sink.send({"type": "token", "text": fragment})
    ctx.observer.mark_evidence_complete(
        plan=ctx.final_plan or ctx.initial_plan,
        metadata=dict(ctx.evidence_state),
        model=ctx.observer.decision_model,
        context=ctx.observer.decision_context,
    )
    return {"stage": "direct_answer"}


async def invalid_prepare_node(_state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> ChatOptInState:
    ctx = runtime.context
    ctx.bundle.trace.record["evidence_search"] = dict(ctx.evidence_state)
    ctx.final_plan = ctx.build_final(ctx.initial_available, ())
    final_retained = retained_chunks(ctx.final_plan, ctx.initial_available)
    final_images = merge_images(ctx.initial_images, checked_images(ctx.final_plan.get("supplied_images", ())))
    supplied = union_chunks(ctx.initial_retained, final_retained)
    try:
        ctx.revalidate(supplied, supplied_images=final_images)
    except (Conflict, InvalidInput):
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("snapshot_changed", INVALID_OUTPUT)
        return {"route": "error", "stage": "invalid_prepare"}
    ctx.evidence_state["final_chunk_ids"] = [str(source["chunk_id"]) for source in final_retained]
    ctx.evidence_state["retained_new_chunk_ids"] = []
    return {"stage": "invalid_prepare"}


async def lookup_node(_state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> ChatOptInState:
    ctx = runtime.context
    try:
        ctx.revalidate(ctx.initial_retained, supplied_images=ctx.initial_images)
    except (Conflict, InvalidInput):
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("snapshot_changed", INVALID_OUTPUT)
        return {"route": "error", "stage": "lookup"}
    ctx.evidence_state["lookup_count"] = 1
    query = ctx.observer.search_query or ""
    lookup_task = asyncio.create_task(ctx.lookup(query, file_ids=ctx.evidence_scope))
    try:
        await _emit_evidence_status(ctx, "searching")
        result = await lookup_task
    except asyncio.CancelledError:
        lookup_task.cancel()
        await asyncio.wait({lookup_task})
        raise
    except Exception:  # noqa: BLE001 - retrieval boundary
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("lookup_failed", LOOKUP_ERROR)
        return {"route": "error", "stage": "lookup"}
    finally:
        if not lookup_task.done():
            lookup_task.cancel()
            await asyncio.wait({lookup_task})
    ctx.latest_search_result = result
    try:
        returned, mode, search_warning = validate_lookup_result(result, ctx.evidence_scope, ctx.initial_available)
    except InvalidInput:
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("invalid_lookup_result", LOOKUP_ERROR)
        return {"route": "error", "stage": "lookup"}
    returned_ids = [str(source["chunk_id"]) for source in returned]
    ctx.evidence_state["returned_chunk_ids"] = returned_ids
    initial_available_ids = set(ctx.evidence_state["initial_available_chunk_ids"])
    ctx.evidence_state["new_chunk_ids"] = [
        chunk_id for chunk_id in returned_ids if chunk_id not in initial_available_ids
    ]
    ctx.evidence_state["search_mode"] = mode
    ctx.evidence_state["search_warning"] = search_warning
    initial_ids_for_prompt = {str(source["chunk_id"]) for source in ctx.initial_available}
    novel_returned = tuple(source for source in returned if str(source["chunk_id"]) not in initial_ids_for_prompt)
    ctx.observer.lookup_returned = returned
    ctx.observer.lookup_novel = novel_returned
    return {"stage": "lookup"}


async def merge_final_plan_node(_state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> ChatOptInState:
    ctx = runtime.context
    returned = ctx.observer.lookup_returned or ()
    novel = ctx.observer.lookup_novel or ()
    ctx.bundle.trace.record["evidence_search"] = dict(ctx.evidence_state)
    ctx.final_plan = ctx.build_final(ctx.initial_available, novel)
    final_retained = retained_chunks(
        ctx.final_plan,
        merge_scoped_sources(
            ctx.initial_available,
            returned,
            selected_file_ids=set(ctx.evidence_scope),
            max_sources=MAX_SOURCE_REFERENCES,
        ),
    )
    final_images = merge_images(ctx.initial_images, checked_images(ctx.final_plan.get("supplied_images", ())))
    all_supplied = union_chunks(ctx.initial_retained, final_retained)
    try:
        ctx.revalidate(all_supplied, supplied_images=final_images)
    except (Conflict, InvalidInput):
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("snapshot_changed", INVALID_OUTPUT)
        return {"route": "error", "stage": "merge"}
    returned_ids = list(ctx.evidence_state.get("returned_chunk_ids", []))
    initial_ids = set(ctx.evidence_state["initial_available_chunk_ids"])
    final_ids = [str(source["chunk_id"]) for source in final_retained]
    ctx.evidence_state["retained_new_chunk_ids"] = [
        chunk_id for chunk_id in final_ids if chunk_id in set(returned_ids) and chunk_id not in initial_ids
    ]
    ctx.evidence_state["outcome"] = "searched"
    ctx.evidence_state["final_chunk_ids"] = final_ids
    return {"stage": "merge"}


async def route_after_prepare(_state: ChatOptInState, runtime: Runtime[ChatOptInExecutionContext]) -> str:
    if runtime.context.observer.workflow_error is not None:
        return "prepare_publication"
    return "stream_final_answer"


async def stream_final_answer_node(
    _state: ChatOptInState,
    runtime: Runtime[ChatOptInExecutionContext],
) -> ChatOptInState:
    ctx = runtime.context
    plan = ctx.final_plan
    if plan is None:
        ctx.observer.set_workflow_error("evidence_failed", "Evidence search failed.")
        return {"stage": "stream_final"}
    ctx.evidence_state["generation_count"] = int(ctx.evidence_state.get("generation_count", 0)) + 1
    ctx.evidence_state["final_chunk_ids"] = list(ctx.evidence_state.get("final_chunk_ids", []))
    ctx.evidence_state["retained_new_chunk_ids"] = list(ctx.evidence_state.get("retained_new_chunk_ids", []))
    ctx.observer.apply_plan(plan, dict(ctx.evidence_state))
    await _emit_evidence_status(ctx, "answering")
    try:
        stream = ctx.model_backend.stream_chat(
            plan["prompt"],
            ctx.model,
            ctx.think,
            ctx.context_limit,
            plan["prompt_context"],
            generation_lock=ctx.generation_lock,
            response_schema=None,
        )
    except Exception:  # noqa: BLE001 - gateway boundary
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error("provider_failed", PROVIDER_ERROR)
        return {"stage": "stream_final"}
    ctx.provider_stream = stream
    saw_answer_text = False
    completed = False
    response_model: str | None = None
    response_context: dict[str, object] | None = None
    error_code: str | None = None
    try:
        async for event in stream:
            kind = event.get("type")
            if kind in {"token", "thinking"}:
                text = event.get("text")
                if not isinstance(text, str):
                    error_code = "invalid_provider_event"
                    break
                if kind == "token" and text.strip():
                    saw_answer_text = True
                ctx.observer.record_token(kind, text)
                for fragment in text_fragments(text):
                    await ctx.sink.send({"type": kind, "text": fragment})
                continue
            if kind == "done":
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
        ctx.observer.mark_cancelled()
        raise
    except Exception:  # noqa: BLE001 - provider stream boundary
        error_code = "provider_failed"
    finally:
        close_error = await close_stream(stream)
        ctx.provider_stream = None
        task = asyncio.current_task()
        if close_error is not None and (task is None or task.cancelling() == 0):
            error_code = "provider_close_failed"
            completed = False
    task = asyncio.current_task()
    if task is not None and task.cancelling() > 0:
        ctx.observer.mark_cancelled()
        ctx.evidence_state["outcome"] = "cancelled"
        return {"stage": "stream_final"}
    if not completed or not saw_answer_text:
        if saw_answer_text and not completed and error_code is None:
            ctx.evidence_state["outcome"] = "cancelled"
            ctx.observer.mark_cancelled()
            return {"stage": "stream_final"}
        ctx.evidence_state["outcome"] = "error"
        ctx.observer.set_workflow_error(error_code or "incomplete_answer", PROVIDER_ERROR)
        return {"stage": "stream_final"}
    ctx.observer.mark_evidence_complete(
        plan=plan,
        metadata=dict(ctx.evidence_state),
        model=response_model,
        context=response_context,
    )
    return {"stage": "stream_final"}


async def prepare_publication_node(
    _state: ChatOptInState,
    runtime: Runtime[ChatOptInExecutionContext],
) -> ChatOptInState:
    ctx = runtime.context
    ctx.bundle.trace.record["evidence_search"] = dict(ctx.evidence_state)
    if ctx.latest_search_result is not None:
        ctx.bundle.latest_search_result = ctx.latest_search_result
        ctx.bundle.total_retrieval_ms = ctx.total_retrieval_ms
    ctx.publication_outcome = await prepare_optin_publication(ctx.bundle, ctx.observer)
    return {"stage": "prepared"}


def build_optin_execution_graph() -> Any:
    builder = StateGraph(ChatOptInState, context_schema=ChatOptInExecutionContext)
    builder.add_node("evidence_init", evidence_init_node)
    builder.add_node("decision", decision_node)
    builder.add_node("direct_answer", direct_answer_node)
    builder.add_node("invalid_prepare", invalid_prepare_node)
    builder.add_node("lookup", lookup_node)
    builder.add_node("merge_final_plan", merge_final_plan_node)
    builder.add_node("stream_final_answer", stream_final_answer_node)
    builder.add_node("prepare_publication", prepare_publication_node)
    builder.add_edge(START, "evidence_init")
    builder.add_conditional_edges(
        "evidence_init",
        route_after_init,
        {"decision": "decision", "error": "prepare_publication"},
    )
    builder.add_conditional_edges(
        "decision",
        route_after_decision,
        {
            "direct": "direct_answer",
            "invalid": "invalid_prepare",
            "search": "lookup",
            "error": "prepare_publication",
        },
    )
    builder.add_edge("direct_answer", "prepare_publication")
    builder.add_conditional_edges(
        "invalid_prepare",
        route_after_prepare,
        {"stream_final_answer": "stream_final_answer", "prepare_publication": "prepare_publication"},
    )
    builder.add_edge("lookup", "merge_final_plan")
    builder.add_conditional_edges(
        "merge_final_plan",
        route_after_prepare,
        {"stream_final_answer": "stream_final_answer", "prepare_publication": "prepare_publication"},
    )
    builder.add_edge("stream_final_answer", "prepare_publication")
    builder.add_edge("prepare_publication", END)
    return builder.compile()


def optin_execution_graph_callables(compiled: Any) -> list[tuple[str, Callable[..., Any]]]:
    return workflow_graph_callables(compiled)
