"""Document-map section summary admission and execution LangGraph workflows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from lab.document_map_store import get_document_map
from lab.document_map_summary_store import recover_interrupted_attempts, write_summary_attempt
from lab.errors import Conflict, InvalidInput
from lab.runtime_policy import load_runtime_policy
from lab.section_summary import SummaryPlan, build_section_summary_plan
from lab.storage import Store
from lab.workflows.events import EventSink, text_fragments
from lab.workflows.runtime import GraphRun, PublishOnce, invoke_graph
from lab.workflows.summary_publication import (
    SummaryObserver,
    SummaryPublicationBundle,
    SummaryPublicationOutcome,
    publish_summary_cancelled,
    publish_summary_from_observer,
    publish_summary_success,
)

logger = logging.getLogger(__name__)

SUMMARY_ADMISSION_NODE_NAMES: tuple[str, ...] = (
    "recover_attempts",
    "resolve_map",
    "load_policy",
    "plan_fit",
    "write_generating_attempt",
)
SUMMARY_EXECUTION_NODE_NAMES: tuple[str, ...] = (
    "stream_summary",
    "validate_and_publish",
    "publish_failure",
)
SUMMARY_ADMISSION_RECURSION_LIMIT = len(SUMMARY_ADMISSION_NODE_NAMES) + 2
SUMMARY_EXECUTION_RECURSION_LIMIT = len(SUMMARY_EXECUTION_NODE_NAMES) + 2
SUMMARY_STREAM_EVENT_TYPES = frozenset({"token", "thinking"})

RegisterActiveFn = Callable[[str], None]
ListActiveAttemptIdsFn = Callable[[], set[str]]
UnregisterActiveFn = Callable[[str], None]
RegisterRunFn = Callable[[GraphRun], None]


class SummaryAdmissionState(TypedDict, total=False):
    """Routing state for summary admission (heavy values live in context artifacts)."""


class SummaryExecutionState(TypedDict, total=False):
    route: Literal["success", "failure"]


@dataclass
class SummaryAdmissionArtifacts:
    map_record: dict[str, object] | None = None
    runtime_policy: str | None = None
    plan: SummaryPlan | None = None
    attempt_id: str | None = None
    started_at: str | None = None
    attempt: dict[str, object] | None = None


def _new_attempt_id() -> str:
    return uuid4().hex


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _admission_active_ids(ctx: SummaryAdmissionContext) -> set[str]:
    return ctx.list_active_attempt_ids()


@dataclass
class SummaryAdmissionContext:
    """Per-request capabilities and inputs for summary admission."""

    store: Store
    runtime_policy_path: Path
    topic: str
    file_id: str
    section_id: str
    expected_revision: str
    model: str
    context_limit: int
    think: bool | str | None
    register_active: RegisterActiveFn
    list_active_attempt_ids: ListActiveAttemptIdsFn
    artifacts: SummaryAdmissionArtifacts = field(default_factory=SummaryAdmissionArtifacts)
    new_id: Callable[[], str] = field(default=_new_attempt_id)
    now_iso: Callable[[], str] = field(default=_now_iso)


@dataclass
class SummaryExecutionContext:
    """Per-request execution capabilities, observer, and publication latch inputs."""

    model_backend: Any
    generation_lock: asyncio.Lock
    bundle: SummaryPublicationBundle
    observer: SummaryObserver
    sink: EventSink
    publish_once: PublishOnce[SummaryPublicationOutcome]
    plan_messages: list[dict[str, object]]
    prompt_context: dict[str, int | bool]
    requested_model: str
    think: bool | str | None
    context_limit: int
    publication_outcome: SummaryPublicationOutcome | None = None


@dataclass(frozen=True, slots=True)
class SummaryAdmissionResult:
    attempt_id: str
    attempt: dict[str, object]
    plan: SummaryPlan


@dataclass
class SummaryStreamHandle:
    """GraphRun-backed NDJSON stream with started prefix and shielded finish."""

    attempt_id: str
    revision: str
    section_id: str
    attempt: dict[str, object]
    run: GraphRun
    publish_once: PublishOnce[SummaryPublicationOutcome]
    bundle: SummaryPublicationBundle
    observer: SummaryObserver
    unregister_active: UnregisterActiveFn
    release_lease: Callable[[], None]
    register_run: RegisterRunFn
    unregister_run: RegisterRunFn
    _publication_outcome: SummaryPublicationOutcome | None = None
    _closed: bool = False

    def attach_publication_outcome(self, outcome: SummaryPublicationOutcome | None) -> None:
        self._publication_outcome = outcome

    async def finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        from anyio import CancelScope

        with CancelScope(shield=True):
            try:
                await self.run.cancel_and_wait()

                async def publish_cancelled() -> SummaryPublicationOutcome:
                    return await publish_summary_cancelled(self.bundle, self.observer)

                if self._publication_outcome is None or not self._publication_outcome.terminal_persisted:
                    outcome = await self.publish_once.run(publish_cancelled)
                    self._publication_outcome = outcome
            finally:
                self.unregister_active(self.attempt_id)
                self.release_lease()
                self.unregister_run(self.run)

    async def events(self) -> AsyncIterator[str]:
        import json

        def line(event: Mapping[str, object]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        yield line(
            {
                "type": "started",
                "attempt_id": self.attempt_id,
                "revision": self.revision,
                "section_id": self.section_id,
                "attempt": self.attempt,
            }
        )
        self.register_run(self.run)
        try:
            async for event in self.run.events():
                yield line(dict(event))
        finally:
            await self.finish()


async def recover_attempts(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    recover_interrupted_attempts(
        ctx.store,
        ctx.topic,
        ctx.file_id,
        active_attempt_ids=_admission_active_ids(ctx),
        finished_at=ctx.now_iso(),
    )
    return {}


async def resolve_map(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    current = get_document_map(ctx.store, ctx.topic, ctx.file_id)
    if current["status"] != "ready" or current["map"] is None:
        raise Conflict("Rebuild the document map before generating a summary.")
    map_record = current["map"]
    if map_record["revision"] != ctx.expected_revision:
        raise Conflict("The selected document map revision changed. Reload it before generating a summary.")
    ctx.artifacts.map_record = map_record
    return {}


async def load_policy(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    ctx.artifacts.runtime_policy = load_runtime_policy(ctx.runtime_policy_path)
    return {}


async def plan_fit(_state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]) -> SummaryAdmissionState:
    ctx = runtime.context
    art = ctx.artifacts
    if art.map_record is None or art.runtime_policy is None:
        msg = "summary admission plan_fit requires map and policy artifacts"
        raise RuntimeError(msg)
    art.attempt_id = ctx.new_id()
    art.started_at = ctx.now_iso()
    art.plan = build_section_summary_plan(
        art.map_record,
        ctx.section_id,
        runtime_policy=art.runtime_policy,
        model=ctx.model,
        context_limit=ctx.context_limit,
        think=ctx.think,
        attempt_id=art.attempt_id,
        started_at=art.started_at,
    )
    return {}


async def write_generating_attempt(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    art = ctx.artifacts
    if art.plan is None or art.attempt_id is None:
        msg = "summary admission write requires a planned generating attempt"
        raise RuntimeError(msg)
    attempt = art.plan["attempt"]
    write_summary_attempt(ctx.store, ctx.topic, ctx.file_id, attempt)
    art.attempt = attempt
    ctx.register_active(art.attempt_id)
    return {}


async def _close_provider_stream(stream: AsyncIterator[dict[str, object]] | None) -> None:
    if stream is not None and hasattr(stream, "aclose"):
        try:
            await stream.aclose()
        except BaseException as exc:  # noqa: BLE001 - provider cleanup must not mask publication
            logger.error("Section-summary stream cleanup failed (%s)", type(exc).__name__)


async def stream_summary(
    _state: SummaryExecutionState, runtime: Runtime[SummaryExecutionContext]
) -> SummaryExecutionState:
    ctx = runtime.context
    observer = ctx.observer
    stream = ctx.model_backend.stream_chat(
        ctx.plan_messages,
        ctx.requested_model,
        ctx.think,
        ctx.context_limit,
        context_metadata=ctx.prompt_context,
        generation_lock=ctx.generation_lock,
    )
    try:
        async for provider_event in stream:
            kind = provider_event.get("type")
            if kind in {"token", "thinking"}:
                text = provider_event.get("text")
                if not isinstance(text, str):
                    raise InvalidInput("The model stream returned malformed text.")
                observer.record(kind, text)
                for fragment in text_fragments(text):
                    await ctx.sink.send({"type": kind, "attempt_id": ctx.bundle.attempt_id, "text": fragment})
                continue
            if kind == "error":
                message = provider_event.get("message")
                text = message if isinstance(message, str) and message else "The model could not complete this summary."
                observer.mark_provider_error(text)
                return {"route": "failure"}
            if kind != "done":
                raise InvalidInput("The model stream returned an unsupported event.")
            await _close_provider_stream(stream)
            stream = None
            actual_model = provider_event.get("model")
            model_name = actual_model if isinstance(actual_model, str) and actual_model else ctx.requested_model
            observer.mark_completed(model=model_name)
            return {"route": "success"}
        observer.mark_premature_eof()
        return {"route": "failure"}
    except asyncio.CancelledError:
        observer.mark_cancelled()
        raise
    except InvalidInput as exc:
        observer.mark_validation_failure(str(exc))
        return {"route": "failure"}
    except Exception as exc:  # noqa: BLE001 - stream boundary maps unknown failures to generic message
        logger.error("Section-summary stream failed (%s)", type(exc).__name__)
        observer.mark_validation_failure("The section summary could not be completed.")
        return {"route": "failure"}
    finally:
        await _close_provider_stream(stream)


async def validate_and_publish(
    _state: SummaryExecutionState, runtime: Runtime[SummaryExecutionContext]
) -> SummaryExecutionState:
    ctx = runtime.context

    async def publish() -> SummaryPublicationOutcome:
        return await publish_summary_success(ctx.bundle, ctx.observer)

    ctx.publication_outcome = await ctx.publish_once.run(publish)
    return {}


async def publish_failure(
    _state: SummaryExecutionState, runtime: Runtime[SummaryExecutionContext]
) -> SummaryExecutionState:
    ctx = runtime.context

    async def publish() -> SummaryPublicationOutcome:
        return await publish_summary_from_observer(ctx.bundle, ctx.observer)

    ctx.publication_outcome = await ctx.publish_once.run(publish)
    return {}


async def _route_after_stream(state: SummaryExecutionState) -> Literal["validate_and_publish", "publish_failure"]:
    if state.get("route") == "success":
        return "validate_and_publish"
    return "publish_failure"


async def _summary_terminal_events(
    execution_context: SummaryExecutionContext,
    publish_once: PublishOnce[SummaryPublicationOutcome],
    *,
    outcome: dict[str, Any] | None,
    error: BaseException | None,
) -> AsyncIterator[Mapping[str, object]]:
    if execution_context.publication_outcome is not None:
        pub = execution_context.publication_outcome
    elif error is not None and isinstance(error, asyncio.CancelledError):

        async def publish() -> SummaryPublicationOutcome:
            return await publish_summary_cancelled(execution_context.bundle, execution_context.observer)

        pub = await publish_once.run(publish)
        execution_context.publication_outcome = pub
    elif error is not None:

        async def publish() -> SummaryPublicationOutcome:
            execution_context.observer.mark_validation_failure("The section summary could not be completed.")
            return await publish_summary_from_observer(execution_context.bundle, execution_context.observer)

        pub = await publish_once.run(publish)
        execution_context.publication_outcome = pub
    else:
        pub = execution_context.publication_outcome or SummaryPublicationOutcome()
    for event in pub.terminal_events:
        yield event


def compile_summary_admission_graph() -> CompiledStateGraph[SummaryAdmissionState, SummaryAdmissionContext, Any, Any]:
    """Build the summary admission graph (compile once per app)."""
    graph: StateGraph[SummaryAdmissionState, SummaryAdmissionContext] = StateGraph(
        SummaryAdmissionState, context_schema=SummaryAdmissionContext
    )
    graph.add_node("recover_attempts", recover_attempts)
    graph.add_node("resolve_map", resolve_map)
    graph.add_node("load_policy", load_policy)
    graph.add_node("plan_fit", plan_fit)
    graph.add_node("write_generating_attempt", write_generating_attempt)
    graph.add_edge(START, "recover_attempts")
    graph.add_edge("recover_attempts", "resolve_map")
    graph.add_edge("resolve_map", "load_policy")
    graph.add_edge("load_policy", "plan_fit")
    graph.add_edge("plan_fit", "write_generating_attempt")
    graph.add_edge("write_generating_attempt", END)
    return graph.compile()


def compile_summary_execution_graph() -> CompiledStateGraph[SummaryExecutionState, SummaryExecutionContext, Any, Any]:
    """Build the summary execution graph (compile once per app)."""
    graph: StateGraph[SummaryExecutionState, SummaryExecutionContext] = StateGraph(
        SummaryExecutionState, context_schema=SummaryExecutionContext
    )
    graph.add_node("stream_summary", stream_summary)
    graph.add_node("validate_and_publish", validate_and_publish)
    graph.add_node("publish_failure", publish_failure)
    graph.add_edge(START, "stream_summary")
    graph.add_conditional_edges("stream_summary", _route_after_stream)
    graph.add_edge("validate_and_publish", END)
    graph.add_edge("publish_failure", END)
    return graph.compile()


def summary_admission_mermaid(compiled: CompiledStateGraph[Any, Any, Any, Any]) -> str:
    return compiled.get_graph().draw_mermaid()


def summary_execution_mermaid(compiled: CompiledStateGraph[Any, Any, Any, Any]) -> str:
    return compiled.get_graph().draw_mermaid()


async def run_summary_admission(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    context: SummaryAdmissionContext,
) -> SummaryAdmissionResult:
    """Await summary admission; domain errors propagate with original types."""
    await invoke_graph(
        graph,
        {},
        context=context,
        recursion_limit=SUMMARY_ADMISSION_RECURSION_LIMIT,
    )
    art = context.artifacts
    if art.plan is None or art.attempt is None or art.attempt_id is None:
        msg = "summary admission finished without attempt artifacts"
        raise RuntimeError(msg)
    return SummaryAdmissionResult(attempt_id=art.attempt_id, attempt=art.attempt, plan=art.plan)


def build_summary_stream_handle(
    *,
    admitted: SummaryAdmissionResult,
    revision: str,
    section_id: str,
    execution_graph: CompiledStateGraph[Any, Any, Any, Any],
    execution_context: SummaryExecutionContext,
    unregister_active: UnregisterActiveFn,
    release_lease: Callable[[], None],
    register_run: RegisterRunFn,
    unregister_run: RegisterRunFn,
) -> SummaryStreamHandle:
    """Create a GraphRun-backed stream handle after successful admission."""
    handle_holder: list[SummaryStreamHandle] = []

    async def terminal_events(
        outcome: dict[str, Any] | None,
        error: BaseException | None,
    ) -> AsyncIterator[Mapping[str, object]]:
        async for event in _summary_terminal_events(
            execution_context,
            execution_context.publish_once,
            outcome=outcome,
            error=error,
        ):
            yield event
        if handle_holder:
            handle_holder[0].attach_publication_outcome(execution_context.publication_outcome)

    run = GraphRun(
        graph=execution_graph,
        state={},
        context=execution_context,
        recursion_limit=SUMMARY_EXECUTION_RECURSION_LIMIT,
        sink=execution_context.sink,
        terminal_events=terminal_events,
    )
    handle = SummaryStreamHandle(
        attempt_id=admitted.attempt_id,
        revision=revision,
        section_id=section_id,
        attempt=admitted.attempt,
        run=run,
        publish_once=execution_context.publish_once,
        bundle=execution_context.bundle,
        observer=execution_context.observer,
        unregister_active=unregister_active,
        release_lease=release_lease,
        register_run=register_run,
        unregister_run=unregister_run,
    )
    handle_holder.append(handle)
    return handle
