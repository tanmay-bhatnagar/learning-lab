"""Chat admission LangGraph and request entry point."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from lab.chat_prompt import build_chat_prompt
from lab.chat_session import append_user_message, history_messages
from lab.contracts import ChatPromptPlan, CloseableAsyncStream, ModelGateway, Session, StoreProtocol, TopicSettings
from lab.errors import Conflict, DomainError, InvalidInput
from lab.evidence_prompt import build_initial_evidence_prompt
from lab.evidence_result import initial_outcomes, retrieval_warning_for_search_mode
from lab.evidence_snapshot import capture_prompt_context
from lab import query_traces
from lab.learner_context import load_learner_context
from lab.query_traces import (
    duration,
    finalize_record,
    insert_started,
    new_trace_id,
    retrieval_fields,
    started_record,
    trace_path,
)
from lab.retrieval import evidence_messages, search
from lab.runtime_policy import load_runtime_policy
from lab.profile_store import ProfileStore
from lab.storage import read_bytes, read_json
from lab.summary_import import validated_summary_imports
from lab.prerequisite_import import validated_prerequisite_imports
from lab.workflows.chat_evidence import ChatOptInExecutionContext, ChatOptInState, build_optin_execution_graph
from lab.workflows.chat_publication import (
    ChatObserver,
    ChatPublicationBundle,
    ChatPublicationOutcome,
    prepare_ordinary_publication,
)
from lab.workflows.events import EventSink, text_fragments
from lab.workflows.runtime import invoke_graph

logger = logging.getLogger(__name__)

ADMISSION_RECURSION_LIMIT = 9
EXECUTION_RECURSION_LIMIT = 4

CHAT_QUEUED_EVENT_TYPES = frozenset({"token", "thinking", "evidence_status"})

EmbedderFn = Callable[[list[str], str], Awaitable[list[list[float]]]]
RetrieverFn = Callable[..., Awaitable[dict[str, object]]]
LoadSettingsFn = Callable[[StoreProtocol], TopicSettings]


class TopicLease(Protocol):
    def hand_off(self) -> None: ...
    def release(self) -> None: ...


AcquireLeaseFn = Callable[[], Awaitable[TopicLease]]


class ChatAdmissionState(TypedDict, total=False):
    stage: str


@dataclass
class ChatAdmissionArtifacts:
    session: Session | None = None
    selected_records: list[dict[str, object]] = field(default_factory=list)
    attachments: list[dict[str, object]] = field(default_factory=list)
    indexed_ids: list[str] = field(default_factory=list)
    runtime_policy: str | None = None
    learner_context: dict[str, str | None] | None = None
    learning_goal: str = ""
    evidence_snapshot: object | None = None
    evidence_scope: tuple[str, ...] = ()
    capture_files: list[dict[str, object]] | None = None
    search_result: dict[str, object] = field(default_factory=lambda: {"hits": [], "mode": "none"})
    retrieval_ms: float = 0.0
    vision: bool = False
    plan: ChatPromptPlan | None = None
    evidence_prompt_kwargs: dict[str, object] | None = None
    evidence_initial_chunks: tuple[dict[str, object], ...] = ()
    citations: list[dict[str, object]] = field(default_factory=list)


@dataclass
class ChatTraceRecorder:
    trace_id: str
    started_monotonic: float
    trace_file: Path
    record: dict[str, object]
    done: bool = False

    def persist(
        self,
        status: str,
        stage: str,
        *,
        error: dict[str, str] | None = None,
        **updates: object,
    ) -> bool:
        if self.done:
            return False
        final = finalize_record(
            self.record,
            status=status,
            now=datetime.now(UTC).isoformat(),
            stage=stage,
            total_ms=(time.monotonic() - self.started_monotonic) * 1000,
            error=error,
            **updates,
        )
        try:
            changed = query_traces.finalize(self.trace_file, final)
        except Exception as exc:
            logger.error("Query trace finalization failed for %s (%s)", self.trace_id, type(exc).__name__)
            raise
        if changed:
            self.done = True
        return changed


@dataclass
class ChatAdmissionContext:
    store: StoreProtocol
    profile_store: ProfileStore
    model_backend: ModelGateway
    retriever: RetrieverFn | None
    embedder: EmbedderFn
    runtime_policy_path: Path
    topic_id: str
    conversation_id: str
    message: str
    file_ids: list[str]
    model: str
    think: bool | str | None
    context_limit: int
    extra_search: bool
    current_settings: TopicSettings
    trace: ChatTraceRecorder
    save_session: Callable[[Session], None]
    artifacts: ChatAdmissionArtifacts = field(default_factory=ChatAdmissionArtifacts)


class ChatExecutionState(TypedDict, total=False):
    stage: str


@dataclass
class ChatExecutionContext:
    model_backend: ModelGateway
    generation_lock: asyncio.Lock
    sink: EventSink
    observer: ChatObserver
    bundle: ChatPublicationBundle
    prompt: list[dict[str, object]]
    model: str
    think: bool | str | None
    context_limit: int
    publication_outcome: ChatPublicationOutcome | None = None
    provider_stream: CloseableAsyncStream | None = None


@dataclass(frozen=True)
class ChatGraphs:
    admission: CompiledStateGraph[ChatAdmissionState, ChatAdmissionContext, Any, Any]
    execution: CompiledStateGraph[ChatExecutionState, ChatExecutionContext, Any, Any]
    optin_execution: CompiledStateGraph[ChatOptInState, ChatOptInExecutionContext, Any, Any]


@dataclass
class AdmittedChat:
    lease: TopicLease
    session: Session
    plan: ChatPromptPlan
    search_result: dict[str, object]
    retrieval_ms: float
    current_settings: TopicSettings
    trace: ChatTraceRecorder
    started_monotonic: float
    topic_id: str
    conversation_id: str
    message: str
    file_ids: list[str]
    model: str
    think: bool | str | None
    context_limit: int
    extra_search: bool
    evidence_snapshot: object | None = None
    evidence_scope: tuple[str, ...] = ()
    evidence_initial_chunks: tuple[dict[str, object], ...] = ()
    evidence_prompt_kwargs: dict[str, object] | None = None
    evidence_vision: bool = False


@dataclass(frozen=True, slots=True)
class AdmittedOptInEvidence:
    snapshot: object
    scope: tuple[str, ...]
    initial_chunks: tuple[dict[str, object], ...]
    prompt_kwargs: dict[str, object]
    vision: bool


def opt_in_evidence(admitted: AdmittedChat) -> AdmittedOptInEvidence:
    if not admitted.extra_search:
        msg = "opt-in evidence requested for ordinary chat admission"
        raise RuntimeError(msg)
    if admitted.evidence_snapshot is None or admitted.evidence_prompt_kwargs is None:
        msg = "opt-in admission missing evidence capture artifacts"
        raise RuntimeError(msg)
    return AdmittedOptInEvidence(
        snapshot=admitted.evidence_snapshot,
        scope=admitted.evidence_scope,
        initial_chunks=admitted.evidence_initial_chunks,
        prompt_kwargs=admitted.evidence_prompt_kwargs,
        vision=admitted.evidence_vision,
    )


def _rejected(exc: BaseException) -> bool:
    return isinstance(exc, DomainError) and exc.status_code < 500


async def load_session_node(_state: ChatAdmissionState, runtime: Runtime[ChatAdmissionContext]) -> ChatAdmissionState:
    ctx = runtime.context
    session = ctx.store.session(ctx.topic_id, ctx.conversation_id)
    validated_summary_imports(session, ctx.conversation_id)
    validated_prerequisite_imports(session, ctx.conversation_id)
    ctx.artifacts.session = session
    return {"stage": "session_loaded"}


async def select_attachments_node(
    _state: ChatAdmissionState,
    runtime: Runtime[ChatAdmissionContext],
) -> ChatAdmissionState:
    ctx = runtime.context
    attachments: list[dict[str, object]] = []
    selected_records: list[dict[str, object]] = []
    for file_id in dict.fromkeys(ctx.file_ids):
        record = ctx.store.file(ctx.topic_id, file_id)
        if record["status"] != "ready":
            raise Conflict(f"Attachment {record['name']} is not ready; check its conversion error.")
        selected_records.append(record)
        if record.get("index_status") != "ready" and not ctx.extra_search:
            content = read_bytes(ctx.store.file_path(ctx.topic_id, record["markdown_name"])).decode("utf-8")
            attachments.append({"role": "user", "content": f"UNTRUSTED ATTACHMENT ({record['name']}):\n{content}"})
    ctx.artifacts.selected_records = selected_records
    ctx.artifacts.attachments = attachments
    ctx.artifacts.indexed_ids = [
        str(record["id"]) for record in selected_records if record.get("index_status") == "ready"
    ]
    return {"stage": "attachments_selected"}


async def route_after_attachments(
    _state: ChatAdmissionState,
    runtime: Runtime[ChatAdmissionContext],
) -> str:
    return "extra_search" if runtime.context.extra_search else "ordinary"


async def capture_snapshot_node(
    _state: ChatAdmissionState,
    runtime: Runtime[ChatAdmissionContext],
) -> ChatAdmissionState:
    ctx = runtime.context
    if not ctx.artifacts.indexed_ids:
        raise InvalidInput("Select at least one indexed document to enable additional evidence search.")
    captured = capture_prompt_context(
        store=ctx.store,
        profile_store=ctx.profile_store,
        topic_id=ctx.topic_id,
        conversation_id=ctx.conversation_id,
        selected_file_ids=set(ctx.file_ids),
        runtime_policy_path=ctx.runtime_policy_path,
    )
    ctx.artifacts.evidence_snapshot = captured.snapshot
    ctx.artifacts.evidence_scope = tuple(sorted(captured.snapshot.indexed_file_ids))
    context = captured.prompt_context
    ctx.artifacts.runtime_policy = str(context["runtime_policy"])
    ctx.artifacts.learner_context = {
        "learner_context": str(context["learner_context"]),
        "cv_text": context["cv_text"],
        "cv_name": context["cv_name"],
    }
    ctx.artifacts.capture_files = list(context["files"])
    ctx.artifacts.attachments = [
        {
            "role": "user",
            "content": (
                f"UNTRUSTED ATTACHMENT ({next(item['name'] for item in context['files'] if item['id'] == file_id)}):\n{content}"
            ),
        }
        for file_id, content in context["attachments"].items()
    ]
    ctx.artifacts.learning_goal = str(context["learning_goal"])
    return {"stage": "snapshot_captured"}


async def load_context_node(_state: ChatAdmissionState, runtime: Runtime[ChatAdmissionContext]) -> ChatAdmissionState:
    ctx = runtime.context
    ctx.artifacts.runtime_policy = load_runtime_policy(ctx.runtime_policy_path)
    ctx.artifacts.learner_context = load_learner_context(
        ctx.store,
        ctx.profile_store,
        ctx.topic_id,
        ctx.conversation_id,
    )
    ctx.artifacts.learning_goal = str(
        read_json(ctx.store.topic(ctx.topic_id) / "topic.json", {}).get("learning_goal", "")
    )
    return {"stage": "context_loaded"}


async def initial_retrieval_node(
    _state: ChatAdmissionState,
    runtime: Runtime[ChatAdmissionContext],
) -> ChatAdmissionState:
    ctx = runtime.context
    search_result: dict[str, object] = {"hits": [], "mode": "none"}
    path = ctx.store.file_path(ctx.topic_id, "retrieval.sqlite")
    retrieval_started = time.monotonic()
    search_file_ids = list(ctx.artifacts.evidence_scope) if ctx.extra_search else list(ctx.artifacts.indexed_ids)
    if path.exists() and search_file_ids:
        search_fn = ctx.retriever or search
        search_result = await search_fn(
            ctx.store,
            ctx.topic_id,
            ctx.message,
            file_ids=search_file_ids,
            limit=ctx.current_settings.retrieval_top_k,
            embedding_model=ctx.current_settings.embedding_model,
            embedder=ctx.embedder,
        )
    elif search_file_ids:
        if ctx.extra_search:
            records = ctx.artifacts.capture_files or []
        else:
            records = ctx.artifacts.selected_records
        names = ", ".join(record["name"] for record in records if record.get("index_status") == "ready")
        raise Conflict(
            f"Indexed evidence is unavailable for {names}: the topic retrieval index is missing. "
            "Restore retrieval.sqlite or re-upload the selected files before chatting.",
        )
    retrieval_ms = (time.monotonic() - retrieval_started) * 1000
    ctx.artifacts.search_result = search_result
    ctx.artifacts.retrieval_ms = retrieval_ms
    ctx.trace.record = retrieval_fields(
        ctx.trace.record,
        selected_file_ids=list(dict.fromkeys(ctx.file_ids)),
        search_result=search_result,
        retained_ids=set(),
        citations=[],
        retrieval_ms=retrieval_ms,
    )
    if ctx.extra_search:
        ctx.trace.record["evidence_search"] = initial_outcomes()
    return {"stage": "retrieval_complete"}


async def vision_probe_node(_state: ChatAdmissionState, runtime: Runtime[ChatAdmissionContext]) -> ChatAdmissionState:
    ctx = runtime.context
    search_result = ctx.artifacts.search_result
    vision = False
    if search_result.get("hits") or ctx.extra_search:
        try:
            available = await ctx.model_backend.list_models()
            vision = any(
                item.get("id") == ctx.model and item.get("vision") is True for item in available.get("models", [])
            )
        except Exception:  # noqa: BLE001 - vision is optional; any model-list failure falls back to text evidence
            vision = False
    ctx.artifacts.vision = vision
    return {"stage": "vision_probed"}


async def build_prompt_node(_state: ChatAdmissionState, runtime: Runtime[ChatAdmissionContext]) -> ChatAdmissionState:
    ctx = runtime.context
    assert ctx.artifacts.session is not None
    assert ctx.artifacts.learner_context is not None
    assert ctx.artifacts.runtime_policy is not None
    search_result = ctx.artifacts.search_result
    evidence, citations = evidence_messages(
        ctx.store,
        ctx.topic_id,
        search_result.get("hits", []),
        include_images=ctx.artifacts.vision,
    )
    ctx.artifacts.citations = citations
    retrieval_warning = search_result.get("warning")
    if ctx.extra_search:
        retrieval_warning = retrieval_warning_for_search_mode(
            search_result.get("mode"),
            keyword_warning=retrieval_warning,
        )
    retrieval_record: dict[str, object] = {
        "mode": search_result.get("mode", "none"),
        "warning": retrieval_warning,
        "citations": citations,
    }
    if ctx.extra_search:
        retrieval_record["evidence_search"] = initial_outcomes()
    prompt_kwargs = dict(
        history=history_messages(ctx.artifacts.session),
        evidence=evidence,
        citations=citations,
        attachments=ctx.artifacts.attachments,
        question=ctx.message,
        active_topic=ctx.topic_id,
        learning_goal=ctx.artifacts.learning_goal,
        runtime_policy=ctx.artifacts.runtime_policy,
        context_limit=ctx.context_limit,
        retrieval_record=retrieval_record,
        **ctx.artifacts.learner_context,
    )
    if ctx.extra_search:
        ctx.artifacts.evidence_prompt_kwargs = prompt_kwargs
        plan = build_initial_evidence_prompt(
            prompt_kwargs=prompt_kwargs,
            source_chunks=search_result.get("hits", []),
            selected_file_ids=set(ctx.artifacts.evidence_scope),
        )
        ctx.artifacts.evidence_initial_chunks = tuple(search_result.get("hits", []))
        evidence_metadata = initial_outcomes()
        evidence_metadata["initial_available_chunk_ids"] = [
            str(source["chunk_id"]) for source in ctx.artifacts.evidence_initial_chunks
        ]
        plan["retrieval_record"]["evidence_search"] = evidence_metadata
        retrieval_record["evidence_search"] = evidence_metadata
        ctx.trace.record["evidence_search"] = evidence_metadata
    else:
        plan = build_chat_prompt(**prompt_kwargs)
    ctx.artifacts.plan = plan
    return {"stage": "prompt_built"}


async def save_user_node(_state: ChatAdmissionState, runtime: Runtime[ChatAdmissionContext]) -> ChatAdmissionState:
    ctx = runtime.context
    assert ctx.artifacts.session is not None
    assert ctx.artifacts.plan is not None
    session = append_user_message(ctx.artifacts.session, ctx.message, ctx.file_ids)
    ctx.save_session(session)
    ctx.artifacts.session = session
    ctx.trace.record["user_saved"] = True
    ctx.trace.record["user_message_index"] = len(session["messages"]) - 1
    elapsed_preflight = (time.monotonic() - ctx.trace.started_monotonic) * 1000
    plan = ctx.artifacts.plan
    search_result = ctx.artifacts.search_result
    retained_ids = set() if ctx.extra_search else {citation["chunk_id"] for citation in plan["citations"]}
    ctx.trace.record = retrieval_fields(
        ctx.trace.record,
        selected_file_ids=list(dict.fromkeys(ctx.file_ids)),
        search_result=search_result,
        retained_ids=retained_ids,
        citations=[] if ctx.extra_search else ctx.artifacts.citations,
        retrieval_ms=ctx.artifacts.retrieval_ms,
    )
    ctx.trace.record["preflight_ms"] = duration(elapsed_preflight)
    ctx.trace.record["prompt_budget"] = plan["prompt_context"].get("limit")
    return {"stage": "user_saved"}


async def stream_answer_node(
    _state: ChatExecutionState,
    runtime: Runtime[ChatExecutionContext],
) -> ChatExecutionState:
    ctx = runtime.context
    stream = ctx.model_backend.stream_chat(
        ctx.prompt,
        ctx.model,
        ctx.think,
        ctx.context_limit,
        context_metadata=ctx.bundle.prompt_context,
        generation_lock=ctx.generation_lock,
    )
    ctx.provider_stream = stream
    try:
        async for event in stream:
            kind = event.get("type")
            if kind in {"token", "thinking"}:
                text = event.get("text", "")
                if isinstance(text, str) and text:
                    ctx.observer.record_token(kind, text)
                    for fragment in text_fragments(text):
                        await ctx.sink.send({"type": kind, "text": fragment})
                continue
            if kind == "done":
                model = event.get("model") if isinstance(event.get("model"), str) else None
                context = event.get("context") if isinstance(event.get("context"), dict) else {}
                ctx.observer.mark_completed(model=model, context=dict(context))
                return {"stage": "streamed"}
            if kind == "error":
                message = (
                    event.get("message")
                    if isinstance(event.get("message"), str)
                    else "Model reported a generation error."
                )
                ctx.observer.mark_provider_error(message)
                return {"stage": "streamed"}
        ctx.observer.mark_premature_eof()
        return {"stage": "streamed"}
    finally:
        stream = ctx.provider_stream
        if stream is not None:
            try:
                await stream.aclose()
            except Exception as exc:  # noqa: BLE001 - optional cleanup failure is recorded for completed answers
                ctx.observer.stream_close_error = {
                    "stage": "stream_close",
                    "code": "stream_close_failed",
                    "exception_type": type(exc).__name__,
                    "summary": "Model stream cleanup failed.",
                }
                logger.error(
                    "Chat stream cleanup failed for %s (%s)",
                    ctx.bundle.trace_id,
                    type(exc).__name__,
                )
        ctx.provider_stream = None


async def prepare_publication_node(
    _state: ChatExecutionState,
    runtime: Runtime[ChatExecutionContext],
) -> ChatExecutionState:
    ctx = runtime.context
    ctx.publication_outcome = await prepare_ordinary_publication(ctx.bundle, ctx.observer)
    return {"stage": "prepared"}


def build_chat_graphs() -> ChatGraphs:
    """Compile chat admission and ordinary execution graphs once at application composition."""
    admission_builder = StateGraph(ChatAdmissionState, context_schema=ChatAdmissionContext)
    admission_builder.add_node("load_session", load_session_node)
    admission_builder.add_node("select_attachments", select_attachments_node)
    admission_builder.add_node("capture_snapshot", capture_snapshot_node)
    admission_builder.add_node("load_context", load_context_node)
    admission_builder.add_node("initial_retrieval", initial_retrieval_node)
    admission_builder.add_node("vision_probe", vision_probe_node)
    admission_builder.add_node("build_prompt", build_prompt_node)
    admission_builder.add_node("save_user", save_user_node)
    admission_builder.add_edge(START, "load_session")
    admission_builder.add_edge("load_session", "select_attachments")
    admission_builder.add_conditional_edges(
        "select_attachments",
        route_after_attachments,
        {"extra_search": "capture_snapshot", "ordinary": "load_context"},
    )
    admission_builder.add_edge("capture_snapshot", "initial_retrieval")
    admission_builder.add_edge("load_context", "initial_retrieval")
    admission_builder.add_edge("initial_retrieval", "vision_probe")
    admission_builder.add_edge("vision_probe", "build_prompt")
    admission_builder.add_edge("build_prompt", "save_user")
    admission_builder.add_edge("save_user", END)

    execution_builder = StateGraph(ChatExecutionState, context_schema=ChatExecutionContext)
    execution_builder.add_node("stream_answer", stream_answer_node)
    execution_builder.add_node("prepare_publication", prepare_publication_node)
    execution_builder.add_edge(START, "stream_answer")
    execution_builder.add_edge("stream_answer", "prepare_publication")
    execution_builder.add_edge("prepare_publication", END)

    return ChatGraphs(
        admission=admission_builder.compile(),
        execution=execution_builder.compile(),
        optin_execution=build_optin_execution_graph(),
    )


async def admit_chat(
    *,
    store: StoreProtocol,
    profile_store: ProfileStore,
    model_backend: ModelGateway,
    retriever: RetrieverFn | None,
    embedder: EmbedderFn,
    runtime_policy_path: Path,
    acquire_lease: AcquireLeaseFn,
    load_settings_fn: LoadSettingsFn,
    topic_id: str,
    conversation_id: str,
    message: str,
    file_ids: list[str],
    model: str,
    think: bool | str | None,
    context_limit: int,
    extra_search: bool,
    admission_graph: CompiledStateGraph[ChatAdmissionState, ChatAdmissionContext, Any, Any],
) -> AdmittedChat:
    """Run chat preflight: trace, lease, admission graph, single user save."""
    store.topic(topic_id)
    started = time.monotonic()
    trace_id = new_trace_id()
    record: dict[str, object] = started_record(
        topic_id=topic_id,
        conversation_id=conversation_id,
        message_chars=len(message),
        model=model,
        think=think,
        context_limit=context_limit,
        embedding_model=None,
        retrieval_top_k=None,
        now=datetime.now(UTC).isoformat(),
        trace_id=trace_id,
    )
    if extra_search:
        record["evidence_search"] = initial_outcomes()
    record["selected_file_ids"] = list(dict.fromkeys(file_ids))
    trace_file = trace_path(store.topic(topic_id))
    insert_started(trace_file, record)
    trace = ChatTraceRecorder(
        trace_id=trace_id,
        started_monotonic=started,
        trace_file=trace_file,
        record=record,
    )

    def save(session: Session) -> None:
        if conversation_id == "default":
            store.save_session(topic_id, session)
        else:
            store.save_session(topic_id, session, conversation_id)

    lease: TopicLease | None = None
    try:
        current = load_settings_fn(store)
        trace.record = {
            **trace.record,
            "embedding_model": current.embedding_model,
            "retrieval_top_k": current.retrieval_top_k,
        }
        lease = await acquire_lease()
    except BaseException as exc:
        status = (
            "cancelled"
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
            else "rejected"
            if _rejected(exc)
            else "error"
        )
        code = "topic_busy" if isinstance(exc, Conflict) else "preflight_failed"
        trace.persist(
            status,
            "preflight",
            error={
                "stage": "preflight",
                "code": code,
                "exception_type": type(exc).__name__,
                "summary": "Chat could not enter preflight.",
            },
        )
        raise

    context = ChatAdmissionContext(
        store=store,
        profile_store=profile_store,
        model_backend=model_backend,
        retriever=retriever,
        embedder=embedder,
        runtime_policy_path=runtime_policy_path,
        topic_id=topic_id,
        conversation_id=conversation_id,
        message=message,
        file_ids=file_ids,
        model=model,
        think=think,
        context_limit=context_limit,
        extra_search=extra_search,
        current_settings=current,
        trace=trace,
        save_session=save,
    )
    try:
        await invoke_graph(admission_graph, {}, context=context, recursion_limit=ADMISSION_RECURSION_LIMIT)
    except BaseException as exc:
        lease.release()
        status = (
            "cancelled"
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
            else "rejected"
            if _rejected(exc)
            else "error"
        )
        trace.persist(
            status,
            "preflight",
            error={
                "stage": "preflight",
                "code": "preflight_failed",
                "exception_type": type(exc).__name__,
                "summary": "Chat preflight did not complete.",
            },
        )
        raise

    assert context.artifacts.session is not None
    assert context.artifacts.plan is not None
    lease.hand_off()
    return AdmittedChat(
        lease=lease,
        session=context.artifacts.session,
        plan=context.artifacts.plan,
        search_result=context.artifacts.search_result,
        retrieval_ms=context.artifacts.retrieval_ms,
        current_settings=current,
        trace=trace,
        started_monotonic=started,
        topic_id=topic_id,
        conversation_id=conversation_id,
        message=message,
        file_ids=file_ids,
        model=model,
        think=think,
        context_limit=context_limit,
        extra_search=extra_search,
        evidence_snapshot=context.artifacts.evidence_snapshot,
        evidence_scope=context.artifacts.evidence_scope,
        evidence_initial_chunks=context.artifacts.evidence_initial_chunks,
        evidence_prompt_kwargs=context.artifacts.evidence_prompt_kwargs,
        evidence_vision=context.artifacts.vision,
    )
