"""LangGraph admission and execution for personalized prerequisite generation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from lab.contracts import CloseableAsyncStream, ModelGateway
from lab.document_map_store import get_document_map
from lab.errors import Conflict
from lab.prerequisite_store import write_prerequisite_attempt
from lab.prerequisites import MAX_RESPONSE_BYTES, build_prerequisite_plan, validate_prerequisite_response
from lab.profile_store import ProfileStore
from lab.runtime_policy import load_runtime_policy
from lab.storage import Store
from lab.workflows.events import EventSink
from lab.workflows.prerequisite_publication import (
    PrerequisitePublicationOutcome,
    finalize_success_events,
    provider_error_message,
    publish_after_graph_exception,
    publish_cancelled,
    publish_stream_failure,
    publication_request_from_bundle,
    recover_file_state,
    terminal_attempt_record,
)
from lab.workflows.runtime import GraphRun, PublishOnce, invoke_graph

logger = logging.getLogger(__name__)

PREREQUISITE_ADMISSION_RECURSION_LIMIT = 8


class PrerequisiteAdmissionState(TypedDict, total=False):
    topic_id: str
    file_id: str
    section_id: str
    revision: str
    model: str
    context_limit: int
    think: bool | str | None
    goal: str | None
    attempt_id: str
    assessment_id: str


@dataclass
class PrerequisiteAdmissionArtifacts:
    map_record: dict[str, object] | None = None
    selected_cv: dict[str, object] | None = None
    cv_text: str | None = None
    runtime_policy: str | None = None
    plan: dict[str, object] | None = None
    attempt: dict[str, object] | None = None
    attempt_id: str | None = None
    assessment_id: str | None = None
    started_at: str | None = None


@dataclass(frozen=True, slots=True)
class PrerequisiteAdmissionCapabilities:
    store: Store
    profile_store: ProfileStore
    runtime_policy_path: Path
    now: Callable[[], str]
    new_attempt_ids: Callable[[], tuple[str, str]]
    register_active: Callable[[str], None]


@dataclass
class PrerequisiteAdmissionContext:
    capabilities: PrerequisiteAdmissionCapabilities
    artifacts: PrerequisiteAdmissionArtifacts = field(default_factory=PrerequisiteAdmissionArtifacts)
    topic_id: str = ""
    file_id: str = ""
    section_id: str = ""
    revision: str = ""
    model: str = ""
    context_limit: int = 0
    think: bool | str | None = None
    goal: str | None = None
    active_attempt_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class PrerequisiteAdmitted:
    attempt_id: str
    assessment_id: str
    attempt: dict[str, object]
    plan: dict[str, object]
    selected_cv: dict[str, object]
    cv_text: str


async def recover_and_reconcile(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    recover_file_state(
        ctx.capabilities.store,
        ctx.capabilities.profile_store,
        ctx.topic_id,
        ctx.file_id,
        ctx.active_attempt_ids,
        now=ctx.capabilities.now,
    )
    return {}


async def resolve_map(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    current = get_document_map(ctx.capabilities.store, ctx.topic_id, ctx.file_id)
    if current["status"] != "ready" or current["map"] is None:
        raise Conflict("Build the current document map before generating prerequisites.")
    map_record = current["map"]
    if map_record["revision"] != ctx.revision:
        raise Conflict("The selected document map revision changed. Reload it before generating prerequisites.")
    ctx.artifacts.map_record = map_record
    return {}


async def select_cv(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    profile = ctx.capabilities.profile_store.read_profile()
    selected = next((item for item in profile["cvs"] if item["id"] == profile["active_cv_id"]), None)
    if selected is None or selected["status"] != "ready" or selected["revoked"]:
        raise Conflict("Select a successfully extracted, non-revoked CV before generating prerequisites.")
    cv_text = ctx.capabilities.profile_store.read_extracted_text(selected["id"])
    if hashlib.sha256(cv_text.encode("utf-8")).hexdigest() != selected["extracted_sha256"]:
        raise Conflict("The selected CV text changed. Reload the CV and retry.")
    ctx.artifacts.selected_cv = selected
    ctx.artifacts.cv_text = cv_text
    return {}


async def load_policy(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    ctx.artifacts.runtime_policy = load_runtime_policy(ctx.capabilities.runtime_policy_path)
    return {}


async def plan_fit(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    map_record = ctx.artifacts.map_record
    selected = ctx.artifacts.selected_cv
    cv_text = ctx.artifacts.cv_text
    runtime_policy = ctx.artifacts.runtime_policy
    if map_record is None or selected is None or cv_text is None or runtime_policy is None:
        msg = "Admission artifacts are incomplete before planning."
        raise RuntimeError(msg)
    attempt_id, assessment_id = ctx.capabilities.new_attempt_ids()
    started_at = ctx.capabilities.now()
    plan = build_prerequisite_plan(
        map_record,
        ctx.section_id,
        selected_cv=selected,
        cv_text=cv_text,
        runtime_policy=runtime_policy,
        goal=ctx.goal,
        model=ctx.model,
        context_limit=ctx.context_limit,
        think=ctx.think,
        assessment_id=assessment_id,
        attempt_id=attempt_id,
        started_at=started_at,
    )
    ctx.artifacts.plan = plan
    ctx.artifacts.attempt_id = attempt_id
    ctx.artifacts.assessment_id = assessment_id
    ctx.artifacts.started_at = started_at
    return {"attempt_id": attempt_id, "assessment_id": assessment_id}


async def write_generating_attempt(
    state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    plan = ctx.artifacts.plan
    attempt_id = ctx.artifacts.attempt_id
    assessment_id = ctx.artifacts.assessment_id
    started_at = ctx.artifacts.started_at
    if plan is None or attempt_id is None or assessment_id is None or started_at is None:
        msg = "Admission artifacts are incomplete before persisting the generating attempt."
        raise RuntimeError(msg)
    provenance = plan["provenance"]
    attempt: dict[str, object] = {
        "id": attempt_id,
        "assessment_id": assessment_id,
        "topic_id": ctx.topic_id,
        "file_id": ctx.file_id,
        "map_revision": ctx.revision,
        "section_id": ctx.section_id,
        "status": "generating",
        "started_at": started_at,
        "finished_at": None,
        "provenance": {
            "prompt_version": provenance["prompt_version"],
            "source_sha256": provenance["source_sha256"],
            "runtime_policy_sha256": provenance["runtime_policy_sha256"],
            "cv_id": provenance["cv_id"],
            "cv_text_sha256": provenance["cv_text_sha256"],
            "goal": provenance["goal"],
            "model": ctx.model,
        },
        "diagnostic": None,
    }
    write_prerequisite_attempt(ctx.capabilities.store, ctx.topic_id, ctx.file_id, attempt)
    ctx.capabilities.register_active(attempt_id)
    ctx.artifacts.attempt = attempt
    return {"attempt_id": attempt_id, "assessment_id": assessment_id}


def compile_prerequisite_admission_graph() -> CompiledStateGraph[
    PrerequisiteAdmissionState, PrerequisiteAdmissionContext, Any, Any
]:
    """Build the prerequisite admission graph (compile once per app router)."""
    graph = StateGraph(PrerequisiteAdmissionState, context_schema=PrerequisiteAdmissionContext)
    graph.add_node("recover_and_reconcile", recover_and_reconcile)
    graph.add_node("resolve_map", resolve_map)
    graph.add_node("select_cv", select_cv)
    graph.add_node("load_policy", load_policy)
    graph.add_node("plan_fit", plan_fit)
    graph.add_node("write_generating_attempt", write_generating_attempt)
    graph.add_edge(START, "recover_and_reconcile")
    graph.add_edge("recover_and_reconcile", "resolve_map")
    graph.add_edge("resolve_map", "select_cv")
    graph.add_edge("select_cv", "load_policy")
    graph.add_edge("load_policy", "plan_fit")
    graph.add_edge("plan_fit", "write_generating_attempt")
    graph.add_edge("write_generating_attempt", END)
    return graph.compile()


async def admit_prerequisite_generation(
    graph: CompiledStateGraph[PrerequisiteAdmissionState, PrerequisiteAdmissionContext, Any, Any],
    *,
    capabilities: PrerequisiteAdmissionCapabilities,
    topic_id: str,
    file_id: str,
    section_id: str,
    revision: str,
    model: str,
    context_limit: int,
    think: bool | str | None,
    goal: str | None,
    active_attempt_ids: set[str],
) -> PrerequisiteAdmitted:
    """Run admission preflight and persist the single generating attempt."""
    context = PrerequisiteAdmissionContext(
        capabilities=capabilities,
        topic_id=topic_id,
        file_id=file_id,
        section_id=section_id,
        revision=revision,
        model=model,
        context_limit=context_limit,
        think=think,
        goal=goal,
        active_attempt_ids=active_attempt_ids,
    )
    initial: PrerequisiteAdmissionState = {
        "topic_id": topic_id,
        "file_id": file_id,
        "section_id": section_id,
        "revision": revision,
        "model": model,
        "context_limit": context_limit,
        "think": think,
        "goal": goal,
    }
    await invoke_graph(
        graph,
        initial,
        context=context,
        recursion_limit=PREREQUISITE_ADMISSION_RECURSION_LIMIT,
    )
    artifacts = context.artifacts
    if (
        artifacts.attempt is None
        or artifacts.plan is None
        or artifacts.selected_cv is None
        or artifacts.cv_text is None
        or artifacts.attempt_id is None
        or artifacts.assessment_id is None
    ):
        msg = "Prerequisite admission completed without required artifacts."
        raise RuntimeError(msg)
    return PrerequisiteAdmitted(
        attempt_id=artifacts.attempt_id,
        assessment_id=artifacts.assessment_id,
        attempt=artifacts.attempt,
        plan=artifacts.plan,
        selected_cv=artifacts.selected_cv,
        cv_text=artifacts.cv_text,
    )


PREREQUISITE_PROGRESS_EVENT_TYPES = frozenset({"progress"})

PREREQUISITE_EXECUTION_NODE_NAMES: tuple[str, ...] = (
    "generate_buffered",
    "publish_stream_failure",
    "check_current_inputs",
    "validate_requirements",
    "register_pending",
    "publish_assessment",
)
PREREQUISITE_EXECUTION_RECURSION_LIMIT = len(PREREQUISITE_EXECUTION_NODE_NAMES) + 2

ProviderRoute = Literal["success", "stream_failure"]


class PrerequisiteExecutionState(TypedDict, total=False):
    route: ProviderRoute
    failure_message: str


@dataclass(slots=True)
class PrerequisiteExecutionBundle:
    store: Store
    profile_store: ProfileStore
    model_backend: ModelGateway
    generation_lock: asyncio.Lock
    topic_id: str
    file_id: str
    section_id: str
    revision: str
    model: str
    context_limit: int
    think: bool | str | None
    attempt_id: str
    assessment_id: str
    attempt: dict[str, object]
    plan: dict[str, object]
    selected_cv: dict[str, object]
    cv_text: str
    now: Callable[[], str]


@dataclass
class PrerequisiteExecutionArtifacts:
    content: str = ""
    content_bytes: int = 0
    parsed: dict[str, object] | None = None
    proficiency_revision: int | None = None
    assessment: dict[str, object] | None = None
    completed_attempt: dict[str, object] | None = None
    publication: PrerequisitePublicationOutcome | None = None
    terminal: bool = False
    stream: CloseableAsyncStream | None = None


@dataclass
class PrerequisiteExecutionContext:
    bundle: PrerequisiteExecutionBundle
    sink: EventSink
    artifacts: PrerequisiteExecutionArtifacts = field(default_factory=PrerequisiteExecutionArtifacts)


async def generate_buffered(
    _state: PrerequisiteExecutionState,
    runtime: Runtime[PrerequisiteExecutionContext],
) -> PrerequisiteExecutionState:
    ctx = runtime.context
    bundle = ctx.bundle
    art = ctx.artifacts
    plan = bundle.plan
    stream = bundle.model_backend.stream_chat(
        plan["messages"],
        bundle.model,
        bundle.think,
        bundle.context_limit,
        context_metadata=plan["prompt_context"],
        generation_lock=bundle.generation_lock,
        response_schema=plan["response_schema"],
    )
    art.stream = stream
    try:
        async for provider_event in stream:
            kind = provider_event.get("type")
            if kind == "thinking":
                continue
            if kind == "token":
                text = provider_event.get("text")
                if not isinstance(text, str):
                    return {
                        "route": "stream_failure",
                        "failure_message": "The model stream returned malformed text.",
                    }
                text_bytes = len(text.encode("utf-8"))
                if art.content_bytes + text_bytes > MAX_RESPONSE_BYTES:
                    return {
                        "route": "stream_failure",
                        "failure_message": "The model response exceeded the allowed size; retry generation.",
                    }
                art.content += text
                art.content_bytes += text_bytes
                await ctx.sink.send({"type": "progress", "attempt_id": bundle.attempt_id, "phase": "generating"})
                continue
            if kind == "error":
                message = provider_error_message(provider_event.get("message"))
                return {"route": "stream_failure", "failure_message": message}
            if kind != "done":
                return {
                    "route": "stream_failure",
                    "failure_message": "The model stream returned an unsupported event.",
                }
            await stream.aclose()
            art.stream = None
            return {"route": "success"}
        message = "The model stream ended before completion."
        return {"route": "stream_failure", "failure_message": message}
    finally:
        if art.stream is not None:
            await art.stream.aclose()
            art.stream = None


async def route_after_generate(
    state: PrerequisiteExecutionState,
    runtime: Runtime[PrerequisiteExecutionContext],
) -> ProviderRoute:
    del runtime
    return state.get("route", "success")


async def publish_stream_failure_node(
    state: PrerequisiteExecutionState,
    runtime: Runtime[PrerequisiteExecutionContext],
) -> PrerequisiteExecutionState:
    ctx = runtime.context
    message = state.get("failure_message", "Prerequisite generation could not be completed.")
    request = publication_request_from_bundle(ctx.bundle)
    ctx.artifacts.publication = publish_stream_failure(request, message=message)
    ctx.artifacts.terminal = True
    return {}


async def check_current_inputs(
    _state: PrerequisiteExecutionState,
    runtime: Runtime[PrerequisiteExecutionContext],
) -> PrerequisiteExecutionState:
    ctx = runtime.context
    bundle = ctx.bundle
    provenance = bundle.plan["provenance"]
    latest_map = get_document_map(bundle.store, bundle.topic_id, bundle.file_id)
    if latest_map["status"] != "ready" or latest_map["map"] is None or latest_map["map"]["revision"] != bundle.revision:
        raise Conflict("The source document changed while prerequisites were generating.")
    latest_profile = bundle.profile_store.read_profile()
    latest_cv = next(
        (item for item in latest_profile["cvs"] if item["id"] == latest_profile["active_cv_id"]),
        None,
    )
    latest_text = bundle.profile_store.read_extracted_text(bundle.selected_cv["id"])
    latest_hash = hashlib.sha256(latest_text.encode("utf-8")).hexdigest()
    if (
        latest_cv is None
        or latest_cv["id"] != bundle.selected_cv["id"]
        or latest_cv["status"] != "ready"
        or latest_cv["revoked"]
        or latest_cv["extracted_sha256"] != provenance["cv_text_sha256"]
        or latest_hash != provenance["cv_text_sha256"]
    ):
        raise Conflict("The selected CV changed while prerequisites were generating; retry.")
    return {}


async def validate_requirements(
    _state: PrerequisiteExecutionState,
    runtime: Runtime[PrerequisiteExecutionContext],
) -> PrerequisiteExecutionState:
    ctx = runtime.context
    bundle = ctx.bundle
    ctx.artifacts.parsed = validate_prerequisite_response(
        ctx.artifacts.content,
        sources=bundle.plan["sources"],
        cv_text=bundle.cv_text,
        assessment_id=bundle.assessment_id,
    )
    return {}


async def register_pending(
    _state: PrerequisiteExecutionState,
    runtime: Runtime[PrerequisiteExecutionContext],
) -> PrerequisiteExecutionState:
    ctx = runtime.context
    bundle = ctx.bundle
    parsed = ctx.artifacts.parsed
    if parsed is None:
        msg = "Parsed requirements are required before registration."
        raise RuntimeError(msg)
    provenance = bundle.plan["provenance"]
    proficiency = bundle.profile_store.register_model_requirements(
        parsed["requirements"],
        topic_id=bundle.topic_id,
        assessment_id=bundle.assessment_id,
        selected_cv_id=bundle.selected_cv["id"],
        selected_cv_text_sha256=provenance["cv_text_sha256"],
    )
    ctx.artifacts.proficiency_revision = proficiency["revision"]
    return {}


async def publish_assessment(
    _state: PrerequisiteExecutionState,
    runtime: Runtime[PrerequisiteExecutionContext],
) -> PrerequisiteExecutionState:
    ctx = runtime.context
    bundle = ctx.bundle
    parsed = ctx.artifacts.parsed
    if parsed is None or ctx.artifacts.proficiency_revision is None:
        msg = "Registration artifacts are required before publication."
        raise RuntimeError(msg)
    provenance = bundle.plan["provenance"]
    finished_at = bundle.now()
    assessment: dict[str, object] = {
        "attempt_id": bundle.attempt_id,
        "assessment_id": bundle.assessment_id,
        "topic_id": bundle.topic_id,
        "file_id": bundle.file_id,
        "map_revision": bundle.revision,
        "section_id": bundle.section_id,
        "cv_id": bundle.selected_cv["id"],
        "cv_text_sha256": provenance["cv_text_sha256"],
        "source_sha256": provenance["source_sha256"],
        **parsed,
        "sources": bundle.plan["source_metadata"],
        "finished_at": finished_at,
    }
    completed = terminal_attempt_record(
        bundle.attempt,
        "completed",
        finished_at=finished_at,
        diagnostic=None,
    )
    write_prerequisite_attempt(
        bundle.store,
        bundle.topic_id,
        bundle.file_id,
        completed,
        assessment=assessment,
    )
    ctx.artifacts.assessment = assessment
    ctx.artifacts.completed_attempt = completed
    ctx.artifacts.publication = finalize_success_events(
        attempt_id=bundle.attempt_id,
        assessment=assessment,
        proficiency_revision=ctx.artifacts.proficiency_revision,
        completed_attempt=completed,
    )
    ctx.artifacts.terminal = True
    return {}


def compile_prerequisite_execution_graph() -> CompiledStateGraph[
    PrerequisiteExecutionState, PrerequisiteExecutionContext, Any, Any
]:
    """Build the prerequisite execution graph (compile once per app router)."""
    graph = StateGraph(PrerequisiteExecutionState, context_schema=PrerequisiteExecutionContext)
    graph.add_node("generate_buffered", generate_buffered)
    graph.add_node("publish_stream_failure", publish_stream_failure_node)
    graph.add_node("check_current_inputs", check_current_inputs)
    graph.add_node("validate_requirements", validate_requirements)
    graph.add_node("register_pending", register_pending)
    graph.add_node("publish_assessment", publish_assessment)
    graph.add_edge(START, "generate_buffered")
    graph.add_conditional_edges(
        "generate_buffered",
        route_after_generate,
        {"success": "check_current_inputs", "stream_failure": "publish_stream_failure"},
    )
    graph.add_edge("publish_stream_failure", END)
    graph.add_edge("check_current_inputs", "validate_requirements")
    graph.add_edge("validate_requirements", "register_pending")
    graph.add_edge("register_pending", "publish_assessment")
    graph.add_edge("publish_assessment", END)
    return graph.compile()


async def prerequisite_terminal_events(
    outcome: dict[str, object] | None,
    error: BaseException | None,
    *,
    context: PrerequisiteExecutionContext,
    publish_once: PublishOnce[PrerequisitePublicationOutcome],
) -> AsyncIterator[Mapping[str, object]]:
    del outcome

    async def finalize() -> PrerequisitePublicationOutcome:
        art = context.artifacts
        if art.publication is not None:
            return art.publication
        if error is not None:
            return await publish_after_graph_exception(publication_request_from_bundle(context.bundle), error)
        msg = "Prerequisite generation could not be completed."
        return await publish_after_graph_exception(
            publication_request_from_bundle(context.bundle),
            RuntimeError(msg),
        )

    publication = await publish_once.run(finalize)
    if publication.terminal:
        context.artifacts.terminal = True
    if (
        error is not None
        and not isinstance(error, asyncio.CancelledError)
        and any(event.get("type") == "done" for event in publication.terminal_events)
    ):
        yield {
            "type": "error",
            "attempt_id": context.bundle.attempt_id,
            "message": "The assessment was saved, but a workflow error occurred afterward.",
        }
        return
    for event in publication.terminal_events:
        yield event


@dataclass(frozen=True, slots=True)
class PrerequisiteExecutionHandle:
    run: GraphRun
    context: PrerequisiteExecutionContext
    publish_once: PublishOnce[PrerequisitePublicationOutcome]


def build_prerequisite_graph_run(
    *,
    graph: CompiledStateGraph[PrerequisiteExecutionState, PrerequisiteExecutionContext, Any, Any],
    bundle: PrerequisiteExecutionBundle,
    publish_once: PublishOnce[PrerequisitePublicationOutcome],
) -> PrerequisiteExecutionHandle:
    sink = EventSink(allowed_types=PREREQUISITE_PROGRESS_EVENT_TYPES, capacity=8)
    context = PrerequisiteExecutionContext(bundle=bundle, sink=sink)
    run = GraphRun(
        graph=graph,
        state={},
        context=context,
        recursion_limit=PREREQUISITE_EXECUTION_RECURSION_LIMIT,
        sink=sink,
        terminal_events=lambda outcome, error: prerequisite_terminal_events(
            outcome,
            error,
            context=context,
            publish_once=publish_once,
        ),
    )
    return PrerequisiteExecutionHandle(run=run, context=context, publish_once=publish_once)


async def finalize_prerequisite_run(
    handle: PrerequisiteExecutionHandle,
    *,
    unregister_active: Callable[[str], None],
    attempt_id: str,
) -> None:
    await handle.run.cancel_and_wait()
    stream = handle.context.artifacts.stream
    if stream is not None:
        await stream.aclose()
    if not handle.context.artifacts.terminal:

        async def cancel_publish() -> PrerequisitePublicationOutcome:
            return await publish_cancelled(
                publication_request_from_bundle(handle.context.bundle),
                already_terminal=handle.context.artifacts.terminal,
            )

        publication = await handle.publish_once.run(cancel_publish)
        if publication.terminal:
            handle.context.artifacts.terminal = True
    unregister_active(attempt_id)
